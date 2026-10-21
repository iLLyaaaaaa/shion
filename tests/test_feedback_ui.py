"""交互打磨集成测试：实际 Qt 手势、菜单、绘制与存档，使用假时钟。"""
import os
from datetime import timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QImage, QMouseEvent
from PySide6.QtTest import QTest

from shion.behavior import JUMP_DURATION
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


@pytest.mark.parametrize("label,kind", [("跳一跳", "jump"), ("转个身", "turn"), ("朝向鼠标", "face")])
def test_action_menu_dispatches_the_selected_action(env, label, kind):
    menu = env.ctl.build_menu()
    actions = find_action(menu, "动作").menu()
    assert [a.text() for a in actions.actions()] == ["跳一跳", "转个身", "朝向鼠标", "去睡觉", "趴一会儿"]
    find_action(actions, label).trigger()
    assert env.win.motion_active
    if kind == "jump":
        assert env.win._jump_start is not None
    elif kind == "turn":
        assert env.win._turn_start is not None
    else:
        assert env.win.displayed_sprite in ("turn_2", "turn_8")


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


def test_jump_does_not_clip_changes_mask_and_returns_to_same_feet(env):
    w = env.win
    w.set_state("done", animate=False)  # 静止基准，working 有轻呼吸，neglect2 有慢摇。
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


def move_global(w, gp):
    event = QMouseEvent(QEvent.MouseMove, QPointF(w.mapFromGlobal(gp)), QPointF(gp),
                        Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    w.mouseMoveEvent(event)


def test_real_drag_reversals_trigger_dizzy_only_after_landing(env):
    w = env.win
    w.release_to_taskbar = True
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
