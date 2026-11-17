"""交互打磨集成测试：实际 Qt 手势、菜单、绘制与存档，使用假时钟。"""
import os
from datetime import timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QImage, QMouseEvent
from PySide6.QtTest import QTest

from shion.behavior import LEGACY_JUMP_DURATION
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


def test_action_menu_dispatches_the_selected_action(env):
    menu = env.ctl.build_menu()
    actions = find_action(menu, "动作").menu()
    assert [a.text() for a in actions.actions()] == ["跳一跳", "去睡觉", "趴一会儿"]
    find_action(actions, "跳一跳").trigger()
    assert env.win.motion_active
    assert env.win._jump_start is not None


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


@pytest.mark.parametrize("action", ["jump", "expression", "talk"])
def test_idle_actions_keep_final_window_position(env, action, monkeypatch):
    env.win.place_default()
    original = env.win.pos()
    monkeypatch.setattr(env.ctl._idle, "step", lambda *args: action)
    env.ctl.tick()
    if action == "talk":
        assert env.said[-1] in env.ctl.lines._lines["time_noon"]
    env.win.advance_to(env.mono[0] + LEGACY_JUMP_DURATION + 0.1)
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
    env.mono[0] += LEGACY_JUMP_DURATION / 2
    w.advance_to(env.mono[0])
    raised = pixels(w)
    assert not np.any(raised[0, :, 3])
    ys, xs = np.where(raised[:, :, 3] > 0)
    assert all(w.mask().contains(QPoint(int(x), int(y))) for x, y in zip(xs, ys))
    assert ys.max() < np.where(original[:, :, 3] > 0)[0].max()
    env.mono[0] += LEGACY_JUMP_DURATION / 2
    w.advance_to(env.mono[0])
    # V3 的发丝/呼吸会让像素有细微差别，这里比脚底位置：落回原处
    assert np.where(pixels(w)[:, :, 3] > 0)[0].max() == np.where(original[:, :, 3] > 0)[0].max()


def move_global(w, gp):
    event = QMouseEvent(QEvent.MouseMove, QPointF(w.mapFromGlobal(gp)), QPointF(gp),
                        Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    w.mouseMoveEvent(event)


def test_real_drag_reversals_trigger_dizzy_only_after_landing(env):
    """V3：捏脸颊上提并被判定为“晃过”（判定本身见 test_v3_gestures 的三次晃动用例）→ 松手落地后才晕，晕不抢掉拖动台词。"""
    from tests.test_v3_gestures import find
    w = env.win
    w.release_to_taskbar = True
    w.place_default()
    w.consume_shaken = lambda: True
    point = find(w, "cheek")
    initial = w.mapToGlobal(point)
    QTest.mousePress(w, Qt.LeftButton, Qt.NoModifier, point)
    move_global(w, initial + QPoint(0, -150))
    env.advance(0.2)
    gp = initial + QPoint(0, -150)
    QTest.mouseRelease(w, Qt.LeftButton, Qt.NoModifier, w.mapFromGlobal(gp))
    assert w.is_falling and w.sprite_name == "drag"
    env.advance(0.1)
    assert w.sprite_name == "drag"
    env.advance(0.9)
    assert not w.is_falling and w.sprite_name == "dizzy"
    assert len(env.said) == 1 and env.said[-1] in env.ctl.lines._lines["cheek_lift"]
    env.advance(2.5)
    assert w.sprite_name == "idle"


def test_working_interrupts_an_already_started_idle_jump(env):
    env.win.jump(automatic=True)
    env.win.advance_to(env.mono[0] + LEGACY_JUMP_DURATION / 2)
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
