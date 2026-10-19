"""交互打磨集成测试：实际 Qt 手势、菜单、绘制与存档，使用假时钟。"""
import os
from datetime import timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QMouseEvent
from PySide6.QtTest import QTest

from shion.behavior import JUMP_DURATION, WALK_DURATION
from shion.pet_window import MARGIN_BOTTOM, MARGIN_X
from shion.state import EXPRESSIONS, load
from tests.test_controller import Env, BODY, env, find_action, qapp


def test_expression_menu_excludes_internal_sprites_and_is_translated(env):
    for lang in ("zh", "en", "ja"):
        env.ctl.set_language(lang)
        menu = env.ctl.build_menu()
        ui = env.ctl.lines.ui
        expressions = find_action(menu, ui("menu_expression")).menu()
        labels = [a.text() for a in expressions.actions() if a.isCheckable()]
        assert labels == [ui("expression_" + name) for name in EXPRESSIONS] + [ui("menu_fix_expression")]
        assert all(label != "expression_" + name for label, name in zip(labels, EXPRESSIONS))


def test_expression_pin_dialogue_drag_restore_and_restart(env, qapp, tmp_path):
    menu = env.ctl.build_menu()
    expressions = find_action(menu, "表情").menu()
    find_action(expressions, "得意").trigger()
    find_action(expressions, "固定当前表情").trigger()
    assert env.data.fixed_expression == "proud"
    assert "表情已固定" in env.ctl.status_text()
    env.ctl.handle_event("working")
    env.win.patted.emit()
    assert env.win.sprite_name == "proud" and env.said
    env.win.drag_started.emit()
    assert env.win.sprite_name == "drag"
    env.win.drag_finished.emit()
    assert env.win.sprite_name == "proud"
    env.advance(30)
    env.scheduler.flush()
    again = Env(tmp_path)
    try:
        assert again.data.fixed_expression == "proud"
        assert again.win.sprite_name == "proud"
    finally:
        again.close()
    menu2 = env.ctl.build_menu()
    submenu = find_action(menu2, "表情").menu()
    assert find_action(submenu, "固定当前表情").isChecked()
    find_action(submenu, "恢复自动").trigger()
    assert env.data.fixed_expression is None and env.win.sprite_name == "working"


def test_activity_menu_saves_and_checked_item_restores(env):
    menu = env.ctl.build_menu()
    submenu = find_action(menu, "活跃度").menu()
    find_action(submenu, "活泼").trigger()
    assert env.data.activity_level == "lively"
    env.scheduler.flush()
    assert load(env.path).activity_level == "lively"
    again = env.ctl.build_menu()
    assert find_action(find_action(again, "活跃度").menu(), "活泼").isChecked()


@pytest.mark.parametrize("label,kind", [("散步一会儿", "walk"), ("走到屏幕另一边", "cross"), ("跳一跳", "jump"), ("转个身", "turn")])
def test_action_menu_dispatches_the_selected_action(env, label, kind):
    env.win.place_default()
    before = env.win.facing
    menu = env.ctl.build_menu()
    find_action(find_action(menu, "动作").menu(), label).trigger()
    if kind in ("walk", "cross"):
        assert env.win._walk is not None
    elif kind == "jump":
        assert env.win.motion_active and env.win._walk is None
    else:
        assert env.win.facing == -before and not env.win.motion_active


def test_fixed_expression_keeps_nudge_dialogue_without_autonomous_motion(env, monkeypatch):
    env.ctl.fix_expression(True)
    bounced = []
    monkeypatch.setattr(env.win, "bounce", lambda: bounced.append(True))
    env.ctl.handle_event("stop")
    env.advance(300)
    assert not bounced
    assert env.said[-1] in env.ctl.lines._lines["nudge"]
    assert env.win.sprite_name == "idle"


@pytest.mark.parametrize("block", ["working", "fixed", "sleep", "quiet"])
def test_idle_actions_pause_in_blocked_states(env, block):
    env.ctl.tick()
    assert env.ctl._idle.next_at is not None
    if block == "working":
        env.ctl.handle_event("working")
        env.win.patted.emit()
    elif block == "fixed":
        env.ctl.fix_expression(True)
    elif block == "quiet":
        env.ctl.set_activity("quiet")
    else:
        env.advance(900)
    env.advance(1)
    assert env.ctl._idle.next_at is None
    assert not env.win.motion_active
    assert env.win._animator.calm


@pytest.mark.parametrize("action", ["turn", "face", "jump", "expression", "talk"])
def test_idle_actions_keep_final_window_position(env, action, monkeypatch):
    env.win.place_default()
    original = env.win.pos()
    monkeypatch.setattr(env.ctl._idle, "step", lambda *args: action)
    env.ctl.tick()
    if action == "talk":
        assert env.said[-1] in env.ctl.lines._lines["idle_talk"]
    env.win.advance_to(env.mono[0] + JUMP_DURATION + 0.1)
    assert env.win.pos() == original


def pixels(win):
    img = win.render_frame().convertToFormat(QImage.Format_RGBA8888)
    return np.frombuffer(img.constBits(), dtype=np.uint8).reshape(img.height(), img.bytesPerLine() // 4, 4)[:, :img.width()].copy()


def pixmap_pixels(pix):
    img = pix.toImage().convertToFormat(QImage.Format_RGBA8888)
    return np.frombuffer(img.constBits(), dtype=np.uint8).reshape(img.height(), img.bytesPerLine() // 4, 4)[:, :img.width()].copy()


@pytest.mark.parametrize("state", ["idle", "happy", "dizzy", "drag", "working"])
def test_mirror_pixels_and_mask_keep_anchor_and_transparent_corners(env, state):
    w = env.win
    w.set_state(state, animate=False)
    original_pos = w.pos()
    before = pixels(w)
    w.turn()
    after = pixels(w)
    # 源贴图必须逐像素镜像；高 DPI -> 逻辑尺寸的 Qt 缩小滤波允许亚像素舍入，
    # 渲染层独立检验脚底和镜像位置，不能要求非整数倍率下每个颜色完全相同。
    source = pixmap_pixels(w._pixmaps[state])
    mirrored = pixmap_pixels(w._mirrored_pixmaps[state])
    assert np.array_equal(source[:, ::-1], mirrored)
    expected = before[:, ::-1, 3]
    actual = after[:, :, 3]
    ey, ex = np.where(expected > 0)
    ay, ax = np.where(actual > 0)
    assert (ex.min(), ex.max(), ey.min(), ey.max()) == (ax.min(), ax.max(), ay.min(), ay.max())
    foot_y = max(0, ay.max() - 7)
    cols = np.arange(actual.shape[1])
    def foot_center(alpha):
        weights = alpha[foot_y:].sum(axis=0)
        return (weights * cols).sum() / weights.sum()
    assert abs(foot_center(expected) - foot_center(actual)) < 0.1
    assert w.pos() == original_pos
    ys, xs = np.where(after[:, :, 3] > 0)
    assert all(w.mask().contains(QPoint(int(x), int(y))) for x, y in zip(xs, ys))
    assert not w.mask().contains(QPoint(0, 0))


def test_jump_does_not_clip_changes_mask_and_returns_to_same_feet(env):
    w = env.win
    w.set_state("working", animate=False)
    original = pixels(w)
    w.jump()
    env.mono[0] += JUMP_DURATION / 2
    w.advance_to(env.mono[0])
    raised = pixels(w)
    assert not np.any(raised[0, :, 3])
    ys, xs = np.where(raised[:, :, 3] > 0)
    assert all(w.mask().contains(QPoint(int(x), int(y))) for x, y in zip(xs, ys))
    assert ys.max() < np.where(original[:, :, 3] > 0)[0].max()
    env.mono[0] += JUMP_DURATION / 2
    w.advance_to(env.mono[0])
    assert np.array_equal(original, pixels(w))


def test_walk_finishes_on_new_saved_position_and_press_interrupts_immediately(env):
    w = env.win
    w.place_default()
    start = w.x()
    env.ctl.do_action("cross")
    assert w.motion_active
    env.advance(0.5)
    assert w.x() != start
    QTest.mousePress(w, Qt.LeftButton, Qt.NoModifier, BODY)
    stopped = w.x()
    assert not w.motion_active
    assert env.data.window["x"] == stopped
    QTest.mouseRelease(w, Qt.LeftButton, Qt.NoModifier, BODY)
    env.advance(5)
    assert w.x() == stopped
    env.ctl.do_action("cross")
    env.advance(100)
    assert not w.motion_active
    avail = QGuiApplication.primaryScreen().availableGeometry()
    assert avail.left() <= w.x() + MARGIN_X
    assert w.x() + w.width() - MARGIN_X <= avail.right() + 1
    assert w.y() + w.height() - MARGIN_BOTTOM == avail.bottom() + 1
    assert env.data.window["x"] == w.x()
    env.scheduler.flush()
    assert load(env.path).window["x"] == w.x()


def test_roam_duration_and_facing_follow_path(env):
    w = env.win
    w.place_default()
    env.ctl.do_action("walk")
    walk = w._walk
    for i in range(1, 20):
        env.advance(0.5)
        assert w.motion_active
        _, _, direction, _ = walk.sample(env.mono[0])
        assert w.facing == direction
    env.advance(0.5)
    assert not w.motion_active
    assert env.mono[0] == 100 + WALK_DURATION
    assert env.data.window["x"] == w.x()


def move_global(w, gp):
    event = QMouseEvent(QEvent.MouseMove, QPointF(w.mapFromGlobal(gp)), QPointF(gp),
                        Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    w.mouseMoveEvent(event)


def test_real_drag_reversals_trigger_dizzy_only_after_landing(env):
    w = env.win
    w.place_default()
    initial = w.mapToGlobal(BODY)
    QTest.mousePress(w, Qt.LeftButton, Qt.NoModifier, BODY)
    for dx in (60, 0, 60, 0):
        env.now += timedelta(seconds=0.2)
        env.mono[0] += 0.2
        move_global(w, initial + QPoint(dx, -150))
    assert w._shake.shaken
    gp = initial + QPoint(0, -150)
    QTest.mouseRelease(w, Qt.LeftButton, Qt.NoModifier, w.mapFromGlobal(gp))
    assert w.is_falling and w.sprite_name == "drag"
    env.advance(0.1)
    assert w.sprite_name == "drag"
    env.advance(0.5)
    assert not w.is_falling and w.sprite_name == "dizzy"
    assert len(env.said) == 1 and env.said[-1] in env.ctl.lines._lines["drag"]
    # 落地表情不受气泡冷却影响，晃晕台词不会抢掉刚说的拖动台词。
    env.advance(2.5)
    assert w.sprite_name == "idle"


@pytest.mark.parametrize("state", ["idle", "happy", "dizzy"])
def test_walk_visible_pixels_stay_within_current_screen(env, state):
    w = env.win
    w.set_height(320)
    w.place_default()
    w.set_state(state, animate=False)
    avail = QGuiApplication.primaryScreen().availableGeometry()
    for _ in range(2):
        w.walk(cross=True)
        duration = w._walk.duration
        for elapsed in (duration - 0.01, duration, duration + 0.225):
            w.advance_to(env.mono[0] + elapsed)
            ys, xs = np.where(pixels(w)[:, :, 3] > 0)
            assert xs.min() + w.x() >= avail.left()
            assert xs.max() + w.x() <= avail.right()


def test_working_interrupts_an_already_started_idle_jump(env):
    env.win.jump(automatic=True)
    env.win.advance_to(env.mono[0] + JUMP_DURATION / 2)
    assert env.win._jump_offset > 0
    env.ctl.handle_event("working")
    assert not env.win.motion_active and env.win._jump_offset == 0


def test_press_and_open_menu_pause_idle_actions(env):
    QTest.mousePress(env.win, Qt.LeftButton, Qt.NoModifier, BODY)
    env.ctl.tick()
    assert env.ctl._idle.next_at is None
    QTest.mouseRelease(env.win, Qt.LeftButton, Qt.NoModifier, BODY)
    env.ctl._menu_open = True
    env.ctl.tick()
    assert env.ctl._idle.next_at is None
