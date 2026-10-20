"""新版动作的边界、变速、真实手势与实际绘制计数。"""
import shutil

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from shion import behavior as b
from shion.debug import PaintCounter
from shion.pet_window import PetWindow, SPRITE_DIR, STATES
from tests.test_controller import BODY, env, qapp
from tests.test_feedback_ui import move_global, pixels


@pytest.mark.parametrize("group", ["jump", "drag"])
@pytest.mark.parametrize("count", [1, 3, 6, 12])
def test_any_contiguous_frame_count_uses_numeric_order(qapp, tmp_path, monkeypatch, group, count):
    import shion.pet_window as module
    for name in STATES:
        shutil.copyfile(SPRITE_DIR / f"{name}.png", tmp_path / f"{name}.png")
    for i in range(1, count + 1):
        shutil.copyfile(SPRITE_DIR / f"{group}_1.png", tmp_path / f"{group}_{i}.png")
    monkeypatch.setattr(module, "SPRITE_DIR", tmp_path)
    w = PetWindow(clock=lambda: 100, autostart=False)
    try:
        names = tuple(f"{group}_{i}" for i in range(1, count + 1))
        assert w._sequences == {group: names}
        if group == "jump":
            w.jump()
            seen = set()
            for elapsed in np.linspace(0, b.JUMP_DURATION - 0.0001, 240):
                w.advance_to(100 + float(elapsed))
                seen.add(w.displayed_sprite)
            assert seen == set(names)
            w.advance_to(100.35)
            assert w._jump_offset == b.JUMP_HEIGHT
        else:
            assert [w._sequence_sprite(group, i * 0.11, 0.11) for i in range(count * 2)] == list(names) * 2
    finally:
        w.close()


def test_jump_smooth_height_boundaries_hold_and_accelerating_descent():
    assert b.jump_sample(0)[0] == 0
    assert b.jump_sample(0.075)[2] == pytest.approx(0.9)
    for t, height in ((0.15, 0), (0.24, 45), (0.44, 45), (0.55, 0)):
        assert b.jump_sample(t)[0] == pytest.approx(height)
        assert abs(b.jump_sample(t - 1e-7)[0] - height) < 0.001
        assert abs(b.jump_sample(t + 1e-7)[0] - height) < 0.001
    assert all(b.jump_sample(float(t))[0] == 45 for t in np.linspace(0.24, 0.44, 20))
    heights = [b.jump_sample(float(t))[0] for t in np.linspace(0.44, 0.55, 5)]
    distances = [-d for d in np.diff(heights)]
    assert all(a < c for a, c in zip(distances, distances[1:]))


@pytest.mark.parametrize("speed,shakes,seconds", [(0, 0, .11), (400, 0, .085),
                                                   (800, 0, .06), (10000, 0, .06),
                                                   (0, 3, .06), (0, 1, .11 - .05 / 3)])
def test_drag_rate_limits_and_shake_acceleration(speed, shakes, seconds):
    playback = b.DragPlayback(0)
    playback.feed(0, speed, shakes)
    playback.advance(10)
    assert 1 / playback.rate == pytest.approx(seconds)


def test_drag_phase_integrates_exactly_across_dropped_frames_and_freezes():
    dense, sparse = b.DragPlayback(0), b.DragPlayback(0)
    for playback in (dense, sparse):
        playback.feed(0, 800, 0)
    for t in np.linspace(0, .4, 25):
        dense.advance(float(t))
    sparse.advance(.4)
    assert dense.phase == pytest.approx(sparse.phase)
    assert dense.rate == pytest.approx(sparse.rate)
    phase = dense.phase
    dense.feed(.4, 0, 0)
    assert dense.phase == phase
    dense.freeze(.5)
    phase, rate = dense.phase, dense.rate
    dense.advance(1)
    assert dense.rate == rate and dense.phase == pytest.approx(phase + rate * .5)


def start_drag(e, *, dx=10, dy=-250):
    w = e.win
    w.place_default()
    initial = w.mapToGlobal(BODY)
    QTest.mousePress(w, Qt.LeftButton, Qt.NoModifier, BODY)
    move_global(w, initial + QPoint(dx, dy))
    return initial


def test_drag_loops_through_fall_and_restores_pinned_state_on_landing(env):
    w = env.win
    env.data.fixed_expression = "proud"
    env.ctl.sync()
    start_drag(env)
    assert w.displayed_sprite == "drag_1"
    # 保持原位，单独检验 110ms 一帧的循环。
    w._last_drag_pos = w.pos()
    for i in range(1, 5):
        env.advance(.11)
        assert w.displayed_sprite == f"drag_{i % 4 + 1}"
    phase = w._drag_playback.phase
    QTest.mouseRelease(w, Qt.LeftButton, Qt.NoModifier, BODY)
    assert w.is_falling and w._drag_playback.phase == pytest.approx(phase)
    env.advance(.11)
    assert w.is_falling and w.displayed_sprite == "drag_2"
    env.advance(1)
    assert w._drag_playback is None and w.displayed_sprite == "proud"


def test_vertical_drag_accelerates_and_regrab_preserves_phase(env):
    w = env.win
    initial = start_drag(env)
    env.advance(.01)
    move_global(w, initial + QPoint(10, -450))
    env.advance(.05)
    assert w._drag_playback.target_rate == pytest.approx(1 / .06)
    QTest.mouseRelease(w, Qt.LeftButton, Qt.NoModifier, BODY)
    env.advance(.05)
    playback = w._drag_playback
    phase = playback.phase
    QTest.mousePress(w, Qt.LeftButton, Qt.NoModifier, BODY)
    gp = w.mapToGlobal(BODY) + QPoint(15, 0)
    move_global(w, gp)
    assert w._drag_playback is playback and playback.phase == phase
    QTest.mouseRelease(w, Qt.LeftButton, Qt.NoModifier, BODY)
    env.advance(1)
    assert w._drag_playback is None


@pytest.mark.parametrize("height", [160, 200, 260, 320])
@pytest.mark.parametrize("direction", [1, -1])
def test_drag_all_frames_tilt_and_mask_are_not_clipped(env, height, direction):
    w = env.win
    w.set_height(height)
    w.set_state("drag", animate=False)
    w._drag_playback = b.DragPlayback(100)
    w._animator.set_drag(True, 100)
    w._animator.feed_velocity(1000, 100)
    for i in range(4):
        w.advance_to(100 + i * .11)
        w._animator.feed_velocity(direction * 1000, 100 + i * .11)
        alpha = pixels(w)[:, :, 3]
        ys, xs = np.where(alpha > 0)
        assert ys.min() > 0 and ys.max() < alpha.shape[0] - 1
        assert xs.min() > 0 and xs.max() < alpha.shape[1] - 1
        assert all(w.mask().contains(QPoint(int(x), int(y))) for x, y in zip(xs, ys))
        assert not w.mask().contains(QPoint(0, 0))


def test_paint_counter_reports_paints_per_actual_elapsed_window():
    counter = PaintCounter(0)
    for _ in range(30):
        counter.record()
    assert counter.sample(.49) is None
    assert counter.sample(.5) == 60
    for _ in range(15):
        counter.record()
    assert counter.sample(1.5) == 15
    assert counter.sample(2) == 0


def test_fps_only_counts_pet_paints_and_follows_without_focus_or_input(qapp, monkeypatch):
    monkeypatch.setenv("SHION_DEBUG", "1")
    clock = [100.0]
    w = PetWindow(clock=lambda: clock[0], autostart=False)
    try:
        w.place_default()
        w.show()
        qapp.processEvents()
        overlay = w._fps_overlay
        assert overlay.isVisible() and overlay.timer.isActive()
        assert overlay.windowFlags() & Qt.WindowTransparentForInput
        assert overlay.windowFlags() & Qt.WindowDoesNotAcceptFocus
        assert overlay.testAttribute(Qt.WA_ShowWithoutActivating)
        assert overlay.focusPolicy() == Qt.NoFocus
        overlay.counter.reset(100)
        w.repaint()
        qapp.processEvents()
        assert overlay.counter.paints > 0
        before = overlay.counter.paints
        w.render_frame()
        w.advance_to(100)
        overlay.repaint()
        assert overlay.counter.paints == before
        clock[0] = 100.5
        overlay.tick()
        assert overlay.text() == f"FPS: {before * 2:.1f}"
        before_pos = overlay.pos()
        w.move(w.x() - 200, w.y() - 100)
        qapp.processEvents()
        assert overlay.pos() != before_pos
        assert w._screen_avail(w.geometry().center()).contains(overlay.geometry())
        w.set_height(320)
        assert w._screen_avail(w.geometry().center()).contains(overlay.geometry())
        w.hide()
        assert not overlay.isVisible() and not overlay.timer.isActive()
        w.show()
        assert overlay.isVisible() and overlay.counter.fps is None
    finally:
        w.close()
    assert not overlay.isVisible() and not overlay.timer.isActive()


def test_normal_mode_creates_no_fps_window(qapp, monkeypatch):
    monkeypatch.delenv("SHION_DEBUG", raising=False)
    w = PetWindow(autostart=False)
    try:
        assert w._fps_overlay is None
    finally:
        w.close()
