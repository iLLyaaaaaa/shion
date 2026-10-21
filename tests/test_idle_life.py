"""待机呼吸/摇摆/换重心：时间线、互斥、几何、点穿及缓存成本。"""
import math
import random

import numpy as np
import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QImage, QPainter

from shion import animator as A
from shion.animator import Animator, Frame, IdleLife
from shion.pet_window import MASK_CACHE_MAX, MARGIN_BOTTOM, PetWindow
from tests.test_controller import env, qapp


def animator(state="idle"):
    a = Animator(random.Random(123))
    a.set_state(state, 0, immediate=True)
    return a


@pytest.mark.parametrize("calm", [False, True])
def test_working_has_its_own_light_breath_even_without_controller(calm):
    a = animator("working")
    a.calm = calm
    assert a.frame(0).sy == 1
    assert a.frame(2).sy == pytest.approx(1.008)
    assert a.frame(4).sy == 1
    assert a.frame(2).angle == 0


def test_slow_sway_period_bounds_and_smooth_start():
    a = animator()
    assert a.frame(0).angle == 0
    assert abs(a.frame(0.001).angle) < 1e-6
    for t, expected in [(1.125, 1.5), (2.25, 0), (3.375, -1.5), (4.5, 0)]:
        assert a.frame(t).angle == pytest.approx(expected, abs=1e-9)
    assert a.frame(0.7).angle == pytest.approx(a.frame(5.2).angle)


@pytest.mark.parametrize("kind,side", [("crouch", 1), ("lean", -1), ("lean", 1)])
def test_weight_shift_curve_has_smooth_ends_and_bounded_peak(kind, side):
    life = IdleLife(random.Random(1))
    life.configure(0, True, "normal")
    life.active = (1, kind, side)
    values = [life.sample(1 + i * A.WEIGHT_DURATION / 200) for i in range(201)]
    if kind == "lean":
        assert values[100][1] == pytest.approx(side * 3)
        assert max(abs(angle) for _, angle in values) <= 3
        assert all(sy == 1 for sy, _ in values)
    else:
        assert min(sy for sy, _ in values) == pytest.approx(.98, abs=.0001)
        assert max(sy for sy, _ in values) == pytest.approx(1.006, abs=.0001)
    for t in (1, 1.6):
        before, after = life.sample(t - 1e-5), life.sample(t + 1e-5)
        assert abs(before[0] - after[0]) < 1e-7
        assert abs(before[1] - after[1]) < .0001


@pytest.mark.parametrize("level,bounds", [("normal", (8, 15)), ("lively", (5, 10))])
def test_random_frequency_and_missed_actions_are_not_replayed(level, bounds):
    life = IdleLife(random.Random(2))
    life.configure(0, True, level)
    last = 0
    for _ in range(100):
        at = life.next_at
        assert bounds[0] <= at - last <= bounds[1]
        life.sample(at)
        last = at
    life.sample(last + 100)
    assert life.next_at > last + 100
    at, _, _ = life.active
    # 过期事件只推进时间线；返回的是当前姿态，而非下一帧补播旧动作。
    if last + 100 - at >= A.WEIGHT_DURATION:
        assert life.sample(last + 100)[0] == 1


@pytest.mark.parametrize("block", ["calm", "drag", "motion", "quiet", "working", "neglect1", "bed", "desk", "sleep"])
def test_ineligible_modes_cancel_and_restart_without_backlog(block):
    a = animator()
    a._idle_life.active = (1, "lean", 1)
    assert a.frame(1.3).angle == pytest.approx(3)
    if block == "calm":
        a.calm = True
    elif block == "drag":
        a.set_drag(True, 1.3)
    elif block == "motion":
        a.idle_enabled = False
    elif block == "quiet":
        a.activity_level = "quiet"
    else:
        a.set_state(block, 1.3, immediate=True)
    assert a.frame(1.31).angle == 0
    assert math.isinf(a._idle_life.next_at)
    a.frame(100)
    a.calm = False
    a.set_drag(False, 100)
    a.idle_enabled = True
    a.activity_level = "normal"
    a.set_state("idle", 100, immediate=True)
    assert a.frame(100).angle == 0
    assert 108 <= a._idle_life.next_at <= 115


def test_dense_and_sparse_updates_match_during_many_micro_actions():
    dense, sparse = animator(), animator()
    for at in (10.2, 31.1, 60.3, 97.4, 200.2):
        start = getattr(dense, "_tested_to", 0)
        for t in np.arange(start, at, 1 / 60):
            dense.frame(float(t))
        assert dense.frame(at) == sparse.frame(at)
        dense._tested_to = at


@pytest.mark.parametrize("action", ["jump", "legacy_jump", "turn", "face", "drag", "fall", "press", "bed", "desk", "fixed", "calm"])
def test_window_actions_block_new_idle_effects(env, action):
    w = env.win
    w.set_state("idle", animate=False)
    env.mono[0] += 1.3
    w._refresh(env.mono[0])
    assert w.frame.angle != 0
    if action in ("jump", "legacy_jump"):
        if action == "legacy_jump":
            w._sequences.pop("jump")
        w.jump()
    elif action == "turn":
        w.turn()
    elif action == "face":
        w.face(1)
    elif action == "drag":
        w._dragging = True
    elif action == "fall":
        w._falling = True
    elif action == "press":
        w._press_global = QPoint(100, 100)
    elif action in ("bed", "desk"):
        w.set_state(action, animate=False)
    elif action == "fixed":
        env.ctl.fix_expression(True)
    else:
        w.set_calm(True)
    w._refresh(env.mono[0])
    assert math.isinf(w._animator._idle_life.next_at)
    # 新增姿态不叠入动作帧或旧跳跃回退。
    if action not in ("bed", "desk"):
        assert w.frame.angle == 0


def test_activity_sync_disables_quiet_and_reschedules_lively(env):
    env.ctl.set_activity("quiet")
    env.win.advance_to(101)
    assert env.win.frame.angle == 0
    assert math.isinf(env.win._animator._idle_life.next_at)
    env.mono[0] = 102
    env.ctl.set_activity("lively")
    env.win.advance_to(102)
    assert 107 <= env.win._animator._idle_life.next_at <= 112


def alpha(image):
    image = image.convertToFormat(QImage.Format_RGBA8888)
    return np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.bytesPerLine() // 4, 4)[:, :image.width(), 3].copy()


@pytest.mark.parametrize("height", [160, 200, 260, 320])
def test_extreme_poses_no_clipping_mask_covers_pixels_and_feet_do_not_move(qapp, height):
    w = PetWindow(height=height, clock=lambda: 100.0, autostart=False)
    try:
        position, size = w.pos(), w.size()
        anchor = (w.x() + w.width() / 2, w.y() + w.height() - MARGIN_BOTTOM)
        poses = [Frame("idle", sy=sy, angle=angle)
                 for sy in (1, 1.025, 1.025 * .98, 1.025 * 1.006)
                 for angle in (-3, -1.501, -.499, 0, .499, 1.501, 3)]
        for f in poses:
            w._frame = f
            w.setMask(w._mask_for(f))
            # 扩大画布重画，直接证明原窗口边界外没有被裁掉的像素。
            pad = 32
            image = QImage(w.width() + pad * 2, w.height() + pad * 2, QImage.Format_ARGB32_Premultiplied)
            image.fill(0)
            painter = QPainter(image)
            painter.setRenderHints(QPainter.SmoothPixmapTransform | QPainter.Antialiasing)
            painter.translate(pad, pad)
            w._draw_sprite(painter, f)
            painter.end()
            full = alpha(image)
            ys, xs = np.where(full > 0)
            assert xs.min() >= pad and xs.max() < image.width() - pad
            assert ys.min() >= pad and ys.max() < image.height() - pad
            ys, xs = np.where(alpha(w.render_frame()) > 0)
            assert all(w.mask().contains(QPoint(int(x), int(y))) for x, y in zip(xs, ys))
            assert not w.mask().contains(QPoint(0, 0))
            assert w.pos() == position and w.size() == size
            assert anchor == (w.x() + w.width() / 2, w.y() + w.height() - MARGIN_BOTTOM)
    finally:
        w.close()


def test_quantized_mask_reuses_region_and_evicts_one_old_entry(qapp):
    w = PetWindow(clock=lambda: 100.0, autostart=False)
    try:
        first = w._mask_for(Frame("idle", sy=1.011, angle=1.1))
        assert w._mask_for(Frame("idle", sy=1.014, angle=1.4)) is first
        old_key = w._mask_key
        for i in range(MASK_CACHE_MAX):
            w._mask_for(Frame("idle", angle=-12 + i * .1, sy=1 + i * .01))
        assert len(w._mask_cache) == MASK_CACHE_MAX
        assert old_key not in w._mask_cache
        recent = w._mask_key
        w._mask_for(Frame("idle", angle=12, sy=1.01))
        assert recent in w._mask_cache
    finally:
        w.close()


def test_slow_idle_reuses_masks_across_600_frames(qapp, monkeypatch):
    w = PetWindow(clock=lambda: 100.0, autostart=False)
    try:
        w._animator._next_blink = math.inf
        w._animator._idle_life.next_at = math.inf
        builds = []
        draw = w._draw_sprite

        def record(painter, frame):
            builds.append(frame)
            draw(painter, frame)

        monkeypatch.setattr(w, "_draw_sprite", record)
        for i in range(600):
            w.advance_to(100 + i / 60)
        assert len(builds) < 30  # 几百个画面姿态只生成少量量化轮廓。
        assert len(w._mask_cache) <= MASK_CACHE_MAX
    finally:
        w.close()


def test_slow_idle_reuses_masks_across_600_frames(qapp, monkeypatch):
    w = PetWindow(clock=lambda: 100.0, autostart=False)
    try:
        w._animator._next_blink = math.inf
        w._animator._idle_life.next_at = math.inf
        builds = []
        draw = w._draw_sprite

        def record(painter, frame):
            builds.append(frame)
            draw(painter, frame)

        monkeypatch.setattr(w, "_draw_sprite", record)
        for i in range(600):
            w.advance_to(100 + i / 60)
        assert len(builds) < 30  # 几百个画面姿态只生成少量量化轮廓。
        assert len(w._mask_cache) <= MASK_CACHE_MAX
    finally:
        w.close()


@pytest.mark.parametrize("kind", ["crouch", "left", "right"])
def test_snapshot_cli_can_preview_weight_shift_and_size(qapp, tmp_path, kind):
    from shion.__main__ import main
    out = tmp_path / f"{kind}.png"
    assert main(["--snapshot", str(out), "--height", "320", "--weight-shift", kind, "--at", ".3"]) == 0
    image = QImage(str(out))
    assert not image.isNull() and image.height() > 320
