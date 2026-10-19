"""控制器测试：离屏 + 假时钟 + 临时存档目录，不需要真实显示器。"""
import os
from datetime import datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from shion import state as S
from shion.controller import PetController
from shion.effects import HeartOverlay
from shion.lines import Lines
from shion.pet_window import MARGIN_TOP, MARGIN_X, PetWindow

T0 = datetime(2026, 10, 19, 12, 0, 0)  # 白天，避开夜间睡眠
BODY = QPoint(MARGIN_X + 60, MARGIN_TOP + 120)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class Env:
    """一套完整的假环境：窗口、状态机、存档、控制器、说话记录。"""

    def __init__(self, tmp_path, save=None):
        self.now = T0
        self.mono = [100.0]
        self.said = []
        self.path = tmp_path / "state.json"
        self.data = save if save is not None else S.load(self.path)
        self.scheduler = S.SaveScheduler(self.path, self.data)
        self.state = S.PetState(self.data, self.now, on_change=self.scheduler.mark_dirty)
        self.win = PetWindow(
            height=self.data.window.get("height", 240), clock=lambda: self.mono[0], autostart=False
        )
        self.overlay = HeartOverlay(clock=lambda: self.mono[0], autostart=False)
        self.ctl = PetController(
            self.win, self.state, self.scheduler, lines=Lines(), overlay=self.overlay,
            now_fn=lambda: self.now, say=self.said.append, autostart=False,
        )

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)
        self.mono[0] += seconds
        self.win.advance_to(self.mono[0])
        self.ctl.tick()

    def close(self):
        self.overlay.close()
        self.win.close()


@pytest.fixture
def env(qapp, tmp_path):
    e = Env(tmp_path)
    yield e
    e.close()


def test_pat_shows_happy_counts_and_spawns_hearts_then_returns_to_idle(env):
    env.win.patted.emit()
    assert env.win.sprite_name == "happy"
    assert env.state.save.affection == 1
    assert env.state.save.stats["pats"] == 1
    assert env.overlay.particles.active
    env.advance(2.0)
    assert env.win.sprite_name == "idle"


def test_pat_occasionally_says_a_pat_line(env):
    for _ in range(5):
        env.win.patted.emit()
    pool = Lines()._lines["pat"]
    assert any(t in pool for t in env.said)
    assert len(env.said) < 5  # 不是每次都说


def test_five_clicks_in_3s_is_stop_ten_in_5s_is_dizzy(env):
    for _ in range(5):
        env.win.clicked.emit()
        env.advance(0.3)
    assert env.win.sprite_name == "stop"
    env.advance(2.5)
    assert env.win.sprite_name == "idle"
    env.advance(10)  # 清掉点击记录
    for _ in range(10):
        env.win.clicked.emit()
        env.advance(0.3)
    assert env.win.sprite_name == "dizzy"
    assert any(t in Lines()._lines["dizzy"] for t in env.said)


def test_drag_signals_switch_sprite_and_save_position(env):
    env.win.place_default()
    env.win.drag_started.emit()
    assert env.win.sprite_name == "drag"
    env.win.move(env.win.x() - 200, env.win.y())
    env.win.drag_finished.emit()
    assert env.win.sprite_name == "idle"
    assert env.data.window["x"] == env.win.x()
    assert env.data.window["y"] == env.win.y()


def test_real_mouse_drag_keeps_drag_sprite_while_falling(env):
    env.win.place_default()
    env.win.show()
    QTest.mousePress(env.win, Qt.LeftButton, Qt.NoModifier, BODY)
    QTest.mouseMove(env.win, BODY + QPoint(0, -300))
    assert env.win.sprite_name == "drag"
    QTest.mouseRelease(env.win, Qt.LeftButton, Qt.NoModifier, BODY + QPoint(0, -300))
    assert env.win.is_falling
    env.advance(0.05)
    assert env.win.sprite_name == "drag"  # 下落途中仍是 drag
    for _ in range(300):
        if not env.win.is_falling:
            break
        env.advance(1 / 60)
    assert not env.win.is_falling
    assert env.win.sprite_name == "idle"
    assert env.data.window["y"] == env.win.y()


def find_action(menu, text):
    for a in menu.actions():
        if a.text() == text:
            return a
    raise AssertionError(f"菜单里没有 {text!r}：{[a.text() for a in menu.actions()]}")


def test_menu_contents(env):
    menu = env.ctl.build_menu()
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert texts == ["夸夸 Claude", "大小", "静音气泡", "开机自启（v1.0）", "关于", "退出"]
    assert not find_action(menu, "开机自启（v1.0）").isEnabled()
    sizes = find_action(menu, "大小").menu().actions()
    assert [a.text() for a in sizes] == ["180", "240", "320", "400"]
    assert [a.isChecked() for a in sizes] == [False, True, False, False]


def test_menu_praise_claude_shows_proud(env):
    menu = env.ctl.build_menu()  # 要留着引用，菜单被回收后动作也没了
    find_action(menu, "夸夸 Claude").trigger()
    assert env.win.sprite_name == "proud"
    assert env.data.affection == 3
    assert env.data.pending_praise == 1
    assert env.said == ["收到！下次见到 Claude 我就告诉它～"]


def test_menu_size_changes_window_and_save_and_checkmark(env):
    env.win.place_default()
    old_h = env.win.height()
    menu = env.ctl.build_menu()
    find_action(find_action(menu, "大小").menu(), "320").trigger()
    assert env.win.sprite_size[1] == 320
    assert env.win.height() > old_h
    assert env.data.window["height"] == 320
    menu2 = env.ctl.build_menu()
    sizes = find_action(menu2, "大小").menu().actions()
    assert [a.isChecked() for a in sizes] == [False, False, True, False]
    avail = QGuiApplication.primaryScreen().availableGeometry()
    assert env.win.y() + env.win.height() - 6 == avail.bottom() + 1  # 仍然贴底


def test_mute_suppresses_lines_but_not_state_changes(env):
    menu = env.ctl.build_menu()
    find_action(menu, "静音气泡").trigger()
    assert env.data.bubble_muted is True
    menu2 = env.ctl.build_menu()
    assert find_action(menu2, "静音气泡").isChecked()
    env.win.clicked.emit()
    env.win.patted.emit()
    assert env.said == []
    assert env.win.sprite_name == "happy"  # 状态照常


def test_double_click_shows_status_after_delay(env):
    env.ctl.status_delay_ms = 20
    for _ in range(3):
        env.win.patted.emit()
    env.said.clear()
    env.win.double_clicked.emit()
    assert env.said == []  # 要等一个双击间隔
    QTest.qWait(80)
    assert len(env.said) == 1
    text = env.said[0]
    assert "今天被摸 3 次" in text and "Claude 完成了 0 个任务" in text and "好感度 3" in text


def test_double_click_followed_by_click_does_not_show_status(env):
    env.ctl.status_delay_ms = 40
    env.win.double_clicked.emit()
    env.win.clicked.emit()  # 其实是连戳
    env.said.clear()
    QTest.qWait(120)
    assert not any("好感度" in t for t in env.said)


def test_status_text_formats_time_together(env):
    assert "已陪伴 0 分钟" in env.ctl.status_text(T0)
    assert "已陪伴 3 小时 5 分钟" in env.ctl.status_text(T0 + timedelta(hours=3, minutes=5))
    assert "已陪伴 2 天 4 小时" in env.ctl.status_text(T0 + timedelta(days=2, hours=4))


def test_save_is_debounced_then_written_and_flushed_on_quit(env):
    env.win.patted.emit()
    assert not env.path.exists()
    env.advance(1.0)
    assert not env.path.exists()
    env.advance(1.5)  # 超过 2 秒
    assert env.path.exists()
    assert S.load(env.path).affection == 1
    env.win.patted.emit()
    quit_signals = []
    env.ctl.quit_requested.connect(lambda: quit_signals.append(1))
    env.ctl.quit()
    assert S.load(env.path).affection == 2  # 退出时立即写
    assert quit_signals == [1]


def test_size_survives_restart(qapp, tmp_path):
    e1 = Env(tmp_path)
    e1.ctl.set_size(180)
    e1.ctl.quit()
    e1.close()
    e2 = Env(tmp_path)
    try:
        assert e2.win.sprite_size[1] == 180
    finally:
        e2.close()


def test_restore_position_uses_saved_x_or_falls_back(qapp, tmp_path):
    avail = QGuiApplication.primaryScreen().availableGeometry()
    e1 = Env(tmp_path)
    e1.data.window["x"] = avail.left() + 100
    e1.ctl.restore_position()
    assert e1.win.x() == avail.left() + 100
    assert e1.win.y() + e1.win.height() - 6 == avail.bottom() + 1
    e1.data.window["x"] = avail.right() + 99999  # 不在任何屏幕上
    e1.ctl.restore_position()
    e1.close()
    e2 = Env(tmp_path)
    e2.data.window["x"] = None
    e2.ctl.restore_position()
    default_x = e2.win.x()
    e2.close()
    assert avail.left() <= default_x <= avail.right()


def test_hover_wakes_sleeping_pet_with_wake_line(env):
    env.advance(16 * 60)
    assert env.win.sprite_name == "sleep"
    env.win.hovered.emit()
    assert env.win.sprite_name != "sleep"
    assert env.said and env.said[-1] in Lines()._lines["wake"]


def test_neglect_return_line_after_long_absence(env):
    env.advance(2 * 3600 + 60)
    env.win.clicked.emit()
    assert env.said[0] in Lines()._lines["neglect_return"]
