"""新版动作的边界、变速、真实手势与实际绘制计数。"""
import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from shion import behavior as b
from shion.debug import PaintCounter
from shion.v3_window import V3PetWindow as PetWindow
from tests.test_controller import env, qapp
from tests.test_feedback_ui import move_global
from tests.test_v3_gestures import find


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
    """V3 里窗口只能被“捏脸颊往上提”拖动：从脸颊处按下再移动。"""
    w = e.win
    w.place_default()
    point = find(w, "cheek")
    initial = w.mapToGlobal(point)
    QTest.mousePress(w, Qt.LeftButton, Qt.NoModifier, point)
    move_global(w, initial + QPoint(dx, dy))
    return initial, point


def test_drag_loops_through_fall_and_restores_pinned_state_on_landing(env):
    """拖动用 DragPlayback 计时，落地后清掉并恢复固定表情（V3 不再切换 drag_N 帧）。"""
    env.win.release_to_taskbar = True  # 验证菜单开关开启后的原重力行为
    w = env.win
    env.data.fixed_expression = "proud"
    env.ctl.sync()
    _, point = start_drag(env)
    assert w.is_dragging and w._drag_playback is not None
    w._last_drag_pos = w.pos()  # 保持原位，单独检验 110ms 一帧的相位推进
    start_phase = w._drag_playback.phase
    env.advance(.44)
    assert w._drag_playback.phase > start_phase
    phase = w._drag_playback.phase
    QTest.mouseRelease(w, Qt.LeftButton, Qt.NoModifier, point)
    assert w.is_falling and w._drag_playback.phase == pytest.approx(phase)
    env.advance(1)
    assert w._drag_playback is None and not w.is_falling and w.displayed_sprite == "proud"


def test_vertical_drag_accelerates_and_regrab_preserves_phase(env):
    env.win.release_to_taskbar = True  # 验证菜单开关开启后的原重力行为
    w = env.win
    initial, point = start_drag(env)
    env.advance(.01)
    move_global(w, initial + QPoint(10, -450))
    env.advance(.05)
    assert w._drag_playback.target_rate == pytest.approx(1 / .06)
    QTest.mouseRelease(w, Qt.LeftButton, Qt.NoModifier, point)
    env.advance(.05)
    playback = w._drag_playback
    phase = playback.phase
    QTest.mousePress(w, Qt.LeftButton, Qt.NoModifier, point)  # 抓住正在下落的桌宠（任意位置）
    gp = w.mapToGlobal(point) + QPoint(15, 0)
    move_global(w, gp)
    assert w._drag_playback is playback and playback.phase == phase
    QTest.mouseRelease(w, Qt.LeftButton, Qt.NoModifier, point)
    env.advance(1)
    assert w._drag_playback is None


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
