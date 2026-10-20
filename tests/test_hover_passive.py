"""真实 Qt 悬停事件只更新光标，不唤醒、不刷新计时、不打断动作。"""
from dataclasses import asdict
from datetime import datetime, timedelta

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QContextMenuEvent, QEnterEvent, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tests.test_controller import env, find_action, qapp
from tests.test_feedback_ui import move_global
from shion.pet_window import MARGIN_TOP, MARGIN_X
from shion.state import EXPRESSIONS


def hover(w):
    """进入、无按键移动、离开；不依赖真实桌面的鼠标位置。"""
    head = QPoint(MARGIN_X + 60, MARGIN_TOP + 20)
    body = QPoint(MARGIN_X + 60, MARGIN_TOP + 170)
    QApplication.sendEvent(w, QEnterEvent(QPointF(head), QPointF(head), QPointF(w.mapToGlobal(head))))
    assert w.cursor().shape() == Qt.OpenHandCursor
    for point, expected in ((body, Qt.ArrowCursor), (head, Qt.OpenHandCursor)):
        QApplication.sendEvent(w, QMouseEvent(
            QEvent.MouseMove, QPointF(point), QPointF(w.mapToGlobal(point)),
            Qt.NoButton, Qt.NoButton, Qt.NoModifier,
        ))
        assert w.cursor().shape() == expected
    QApplication.sendEvent(w, QEvent(QEvent.Leave))
    assert w.cursor().shape() == Qt.ArrowCursor


SCENARIOS = [
    "sleep", "night", "bed", "goodnight", "desk", "auto_desk", "neglect1", "neglect2",
    "working", "paused", "temporary", "idle_expression", "snack",
    "turn", "face", "jump", "auto_turn", "auto_face", "auto_jump", "cheek", "tickle",
] + ["fixed_" + name for name in EXPRESSIONS]


def prepare(e, scenario):
    if scenario == "sleep":
        e.advance(16 * 60)
    elif scenario == "night":
        e.now = datetime(2026, 10, 21, 1)
        e.ctl.sync()
    elif scenario == "goodnight":
        e.ctl.choose_dialogue("talks", "goodnight")
    elif scenario in ("bed", "desk"):
        e.ctl.do_action(scenario)
    elif scenario in ("neglect1", "neglect2", "auto_desk"):
        minutes = 121 if scenario == "neglect2" else 31
        e.data.last_attended = e.now - timedelta(minutes=minutes)
        e.ctl._neglect_checked = True  # 落寞本身不随机换成趴桌。
        if scenario == "auto_desk":
            e.state.rest_at_desk(e.now, automatic=True)
        e.ctl.sync()
    elif scenario.startswith("fixed_"):
        e.ctl.select_expression(scenario.removeprefix("fixed_"))
        e.ctl.fix_expression(True)
    elif scenario == "working":
        e.state.claude_event("working", "", e.now)
        e.ctl.sync()
    elif scenario == "paused":
        e.ctl.stop_work()
    elif scenario == "temporary":
        e.win.patted.emit()
    elif scenario == "idle_expression":
        e.state.idle_expression("happy", e.now)
        e.ctl.sync()
    elif scenario == "snack":
        assert e.state.start_snack(e.now)
        e.ctl.sync()
    elif scenario == "cheek":
        e.win._pose = "cheek_3"
        e.win._pose_until = e.mono[0] + 2
        e.win.advance_to(e.mono[0])
    elif scenario == "tickle":
        e.win._feed_tickle(e.mono[0])
    else:
        automatic = scenario.startswith("auto_")
        name = scenario.removeprefix("auto_")
        args = (1,) if name == "face" else ()
        getattr(e.win, name)(*args, automatic=automatic)
        assert e.win.motion_active


def snapshot(e):
    return (
        asdict(e.data), e.state.current(e.now), e.state._last_activity, e.state._woken_date,
        e.state._menu_sleep, e.state._resting, e.state._resting_auto, e.state._idle_expression,
        e.win.sprite_name, e.win.displayed_sprite, e.win.frame, e.win.geometry(),
        e.win._turn_start, e.win._jump_start, e.win._pose, e.win._pose_until,
        e.win._tickle_start, e.win._tickle_last, e.ctl._idle.next_at, list(e.said),
    )


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_hover_preserves_state_action_timers_and_dialogue(env, scenario, monkeypatch):
    prepare(env, scenario)
    env.win.setToolTip("提示仍由 Qt 显示")
    before = snapshot(env)

    def unexpected_interaction(*args, **kwargs):
        pytest.fail("悬停不应进入状态机的交互入口")

    monkeypatch.setattr(env.state, "interact", unexpected_interaction)
    for _ in range(3):
        hover(env.win)
        assert snapshot(env) == before
        assert env.win.toolTip() == "提示仍由 Qt 显示"


def test_repeated_hover_does_not_postpone_idle_sleep(env):
    env.advance(899)
    assert env.win.sprite_name != "sleep"
    for _ in range(3):
        hover(env.win)
        env.advance(1)
    assert env.win.sprite_name == "sleep"
    assert env.said == []


def test_enter_leave_during_drag_keep_closed_hand_and_dragging(env):
    w = env.win
    point = QPoint(MARGIN_X + 60, MARGIN_TOP + 170)
    QTest.mousePress(w, Qt.LeftButton, Qt.NoModifier, point)
    gp = w.mapToGlobal(point) + QPoint(20, -20)
    move_global(w, gp)
    assert w.is_dragging and w.cursor().shape() == Qt.ClosedHandCursor
    QApplication.sendEvent(w, QEvent(QEvent.Leave))
    QApplication.sendEvent(w, QEnterEvent(QPointF(point), QPointF(point), QPointF(gp)))
    assert w.is_dragging and w.cursor().shape() == Qt.ClosedHandCursor
    QTest.mouseRelease(w, Qt.LeftButton, Qt.NoModifier, w.mapFromGlobal(gp))


@pytest.mark.parametrize("scenario", ["sleep", "night", "bed", "desk", "auto_desk", "turn", "auto_jump"])
def test_browsing_or_cancelling_context_menu_preserves_state_and_motion(env, scenario, monkeypatch):
    prepare(env, scenario)
    before = snapshot(env)
    menu = env.ctl.build_menu()
    visited = []

    class BrowsedMenu:
        def exec(self, pos):
            visited.append(True)
            assert env.ctl._menu_open
            menu.setActiveAction(find_action(menu, "动作"))
            hover(env.win)
            assert snapshot(env) == before
            return None  # 模拟 Esc / 点到菜单外取消，不触发 QAction。

        def deleteLater(self):
            menu.deleteLater()

    monkeypatch.setattr(env.ctl, "build_menu", BrowsedMenu)
    pos = QPoint(MARGIN_X + 60, MARGIN_TOP + 170)
    QApplication.sendEvent(env.win, QContextMenuEvent(
        QContextMenuEvent.Mouse, pos, env.win.mapToGlobal(pos),
    ))
    assert not env.ctl._menu_open
    assert visited == [True]
    assert snapshot(env) == before


@pytest.mark.parametrize("rest", ["bed", "desk"])
@pytest.mark.parametrize("operation", ["click", "pat", "cheek", "tickle", "drag", "double", "menu"])
def test_real_operations_still_leave_sleep_or_desk(env, rest, operation):
    env.ctl.do_action(rest)
    if operation == "click":
        env.win.clicked.emit()
    elif operation == "pat":
        env.win.patted.emit()
    elif operation in ("cheek", "tickle"):
        env.win.gesture.emit("cheek_pull" if operation == "cheek" else "tickle")
    elif operation == "drag":
        env.win.drag_started.emit()
    elif operation == "double":
        env.win.double_clicked.emit()
    else:
        menu = env.ctl.build_menu()
        find_action(find_action(menu, "动作").menu(), env.ctl.lines.ui("action_jump")).trigger()
        assert env.win.motion_active
    assert not env.state._menu_sleep and not env.state._resting
    assert env.win.sprite_name not in ("sleep", "bed", "desk")
