"""跳跃（V3 只用程序跳）、锚点及遮罩的集成测试。"""
import math

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest

from shion.behavior import LEGACY_JUMP_DURATION, LEGACY_JUMP_HEIGHT
from shion.v3_window import V3PetWindow as PetWindow
from tests.test_controller import BODY, env, qapp
from tests.test_feedback_ui import pixels


def legacy_offset(elapsed):
    return LEGACY_JUMP_HEIGHT * math.sin(math.pi * max(0.0, min(1.0, elapsed / LEGACY_JUMP_DURATION)))


@pytest.mark.parametrize("automatic", [False, True])
def test_jump_four_stages_45px_then_lands_with_squash_and_rebound(env, automatic):
    """V3 没有跳跃帧序列：表情不变，只按正弦曲线抬起 LEGACY_JUMP_HEIGHT 再落回，窗口不动，没有落地压扁。"""
    w = env.win
    w.set_state("working", animate=False)
    pos = w.pos()
    w.jump(automatic=automatic)
    assert w.displayed_sprite == "working" and w._jump_offset == 0
    assert w.idle_motion_active == automatic
    for fraction in (0.25, 0.5, 0.75):
        elapsed = LEGACY_JUMP_DURATION * fraction
        env.mono[0] = 100 + elapsed
        w.advance_to(env.mono[0])
        assert w.displayed_sprite == "working"
        assert w._jump_offset == pytest.approx(legacy_offset(elapsed), abs=1e-8)
        assert w.pos() == pos
    assert w._jump_offset == pytest.approx(LEGACY_JUMP_HEIGHT * math.sin(math.pi * 0.75), abs=1e-8)
    env.mono[0] = 100 + LEGACY_JUMP_DURATION
    w.advance_to(env.mono[0])
    assert not w.motion_active and w._jump_offset == 0 and w.pos() == pos
    assert w.frame.sy == pytest.approx(1.0, abs=0.001)  # 没有落地压扁（V3 自己呼吸，V2 的呼吸缩放已去掉）


@pytest.mark.parametrize("action,elapsed", [("jump", 0.2), ("jump", 0.35), ("jump", 1.0)])
def test_motion_does_not_depend_on_dropped_frames(qapp, action, elapsed):
    windows = [PetWindow(clock=lambda: 100.0, autostart=False) for _ in range(2)]
    try:
        for w in windows:
            w.set_state("working", animate=False)
            w.place_default()
            w.jump()
        for i in range(1, int(elapsed * 60) + 1):
            windows[0].advance_to(100 + i / 60)
        for w in windows:
            w.advance_to(100 + elapsed)
        a, b = windows
        assert a.frame == b.frame and a.pos() == b.pos()
        assert a._jump_offset == pytest.approx(b._jump_offset)
        assert a._jump_offset == pytest.approx(legacy_offset(elapsed), abs=1e-8)
    finally:
        for w in windows:
            w.close()


@pytest.mark.parametrize("height", [160, 200, 260, 320])
def test_motion_pixels_are_not_clipped_and_masks_cover_visible_pixels(env, height):
    w = env.win
    w.set_height(height)
    w.set_state("working", animate=False)
    w.place_default()
    for action, times in (("jump", [0, 0.075, 0.15, 0.24, 0.35, 0.44, 0.495]),):
        w.jump()
        start = env.mono[0]
        for elapsed in times:
            env.mono[0] = start + elapsed
            w.advance_to(env.mono[0])
            alpha = pixels(w)[:, :, 3]
            ys, xs = np.where(alpha > 0)
            assert ys.min() > 0 and ys.max() < alpha.shape[0] - 1
            assert xs.min() > 0 and xs.max() < alpha.shape[1] - 1
            assert all(w.mask().contains(QPoint(int(x), int(y))) for x, y in zip(xs, ys))
            assert not w.mask().contains(QPoint(0, 0))


def test_mouse_press_interrupts_jump_without_a_delayed_landing(env):
    w = env.win
    env.ctl.select_expression("working")
    w.jump()
    env.advance(LEGACY_JUMP_DURATION / 2)
    assert w._jump_offset == pytest.approx(LEGACY_JUMP_HEIGHT, abs=1e-6)
    QTest.mousePress(w, Qt.LeftButton, Qt.NoModifier, BODY)
    assert not w.motion_active and w._jump_offset == 0 and w.displayed_sprite == "working"
    env.advance(1)
    assert w.frame.sy == pytest.approx(1.0, abs=.02)  # 没有延迟落地的压扁（落地压扁约 10%）
    assert w.displayed_sprite == "working"
    QTest.mouseRelease(w, Qt.LeftButton, Qt.NoModifier, BODY)


def test_snapshot_cli_exposes_jump_and_drag_sequence_stages(qapp, tmp_path):
    """--jump 在 V3 下拍到起跳的几个时刻，彼此不同（--drag 已随 V2 帧序列删除，见 test_v3_default 的参数拒绝用例）。"""
    from shion.__main__ import main
    frames = []
    for elapsed in ("0.10", "0.25", "0.40"):
        out = tmp_path / f"jump-{elapsed}.png"
        assert main(["--snapshot", str(out), "--jump", "--at", elapsed]) == 0
        img = QImage(str(out)).convertToFormat(QImage.Format_RGBA8888)
        frames.append(bytes(img.constBits()))
    assert len(set(frames)) == 3


def test_snapshot_bubble_does_not_paint_over_jump_at_apex(qapp, tmp_path):
    from shion.app import snapshot
    from shion.bubble import GAP, BubbleWindow
    from shion.pet_window import MARGIN_TOP

    at = LEGACY_JUMP_DURATION / 2
    plain, combined = tmp_path / "jump.png", tmp_path / "jump-bubble.png"
    assert snapshot(str(plain), jump=True, at=at) == 0
    assert snapshot(str(combined), jump=True, at=at, bubble="Hello") == 0
    def rgba(path):
        img = QImage(str(path)).convertToFormat(QImage.Format_RGBA8888)
        return np.frombuffer(img.constBits(), dtype=np.uint8).reshape(
            img.height(), img.bytesPerLine() // 4, 4)[:, :img.width()].copy()
    bubble = BubbleWindow(autostart=False)
    try:
        bubble.say("Hello")
        source, result = rgba(plain), rgba(combined)
        py = max(0, bubble.height() + GAP - (MARGIN_TOP - round(LEGACY_JUMP_HEIGHT)))
        px = (result.shape[1] - source.shape[1]) // 2
        ys, xs = np.where(source[:, :, 3] > 0)
        assert np.array_equal(source[ys, xs], result[ys + py, xs + px])
    finally:
        bubble.close()
