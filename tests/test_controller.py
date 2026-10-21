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
from shion.controller import PetController, pick_screen_rect
from shion.effects import HeartOverlay
from shion.lines import Lines
from shion.pet_window import MARGIN_TOP, MARGIN_X, PetWindow

T0 = datetime(2026, 10, 19, 12, 0, 0)  # 白天，避开夜间睡眠
BODY = QPoint(MARGIN_X + 60, MARGIN_TOP + 170)  # 普通身体区，肚子由专用手势测试覆盖


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class Env:
    """一套完整的假环境：窗口、状态机、存档、控制器、说话记录。"""

    def __init__(self, tmp_path, save=None, *, affection=None):
        self.now = T0
        self.mono = [100.0]
        self.said = []
        self.path = tmp_path / "state.json"
        self.data = save if save is not None else S.load(self.path)
        self.scheduler = S.SaveScheduler(self.path, self.data)
        self.state = S.PetState(self.data, self.now, on_change=self.scheduler.mark_dirty, affection=affection)
        self.win = PetWindow(
            height=self.data.window.get("height", 200), clock=lambda: self.mono[0], autostart=False
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
        self.ctl.dispose()
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
    assert env.state.save.feedback_queue == []
    assert env.overlay.particles.active
    assert len(env.overlay.particles.items(env.mono[0])) == 2
    env.advance(2.0)
    assert env.win.sprite_name == "idle"


def test_continuous_pat_keeps_pair_only_at_start_then_one_every_200ms(env):
    env.data.activity_level = "quiet"
    env.win.patted.emit()
    for _ in range(10):
        env.win.patted.emit()
    assert len(env.overlay.particles.items(env.mono[0])) == 2
    for expected in (3, 4, 5, 6):
        env.advance(0.2)
        env.win.patted.emit()
        assert len(env.overlay.particles.items(env.mono[0])) == expected
    assert env.data.affection == env.data.stats["pats"] == 15
    assert env.data.feedback_queue == []


def test_pat_session_gap_restarts_pair_only_after_one_second(env):
    env.data.activity_level = "quiet"
    env.win.patted.emit()
    assert len(env.overlay.particles.items(env.mono[0])) == 2
    env.advance(1)
    env.win.patted.emit()
    assert len(env.overlay.particles.items(env.mono[0])) == 1
    env.advance(1.001)
    env.win.patted.emit()
    assert len(env.overlay.particles.items(env.mono[0])) == 2


def test_new_pat_pair_is_not_blocked_by_high_priority_speech_or_mute(env):
    env.ctl.handle_event("stop", "好了")
    accepted = list(env.said)
    env.win.patted.emit()
    assert env.said == accepted
    assert len(env.overlay.particles.items(env.mono[0])) == 2
    env.advance(1.001)
    env.ctl.set_muted(True)
    env.win.patted.emit()
    assert len(env.overlay.particles.items(env.mono[0])) == 2
    assert env.data.affection == env.data.stats["pats"] == 2


def test_pat_occasionally_says_a_pat_line(env):
    for _ in range(5):
        env.win.patted.emit()
    pool = Lines()._lines["pat"]
    assert any(t in pool for t in env.said)
    assert len(env.said) < 5  # 不是每次都说


@pytest.mark.parametrize("first,hook,key", [(True, False, "intro"), (False, False, "startup"), (True, True, "intro"), (False, True, "time_noon")])
def test_startup_source_and_first_launch(env, first, hook, key):
    env.ctl.greet_startup(first, from_hook=hook)
    assert len(env.said) == (1 if key else 0)
    if key:
        assert env.said[0] in env.ctl.lines._lines[key]


def test_startup_greeting_respects_mute(env):
    env.data.bubble_muted = True
    env.ctl.greet_startup(True)
    env.ctl.greet_startup(False)
    assert env.said == []


def test_controller_timers_are_precise(env):
    assert env.ctl._timer.timerType() == Qt.PreciseTimer
    assert env.ctl._status_timer.timerType() == Qt.PreciseTimer


def test_random_poke_reaction_reaches_window_and_dialogue(env, monkeypatch):
    monkeypatch.setattr(env.state._rng, "random", lambda: 0.6)
    for _ in range(3):
        env.win.clicked.emit()
        env.advance(0.3)
    assert env.win.sprite_name == "dizzy"
    assert len(env.said) == 1 and env.said[0] in Lines()._lines["poke"]
    # 表情照常变化，低优先级的新台词不能盖掉刚出现的戳台词。
    env.advance(3.1)
    assert env.win.sprite_name == "idle"


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
    env.win.release_to_taskbar = True  # 验证菜单开关开启后的原重力行为
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
    assert texts == ["对话", "工作遥控", "表情", "活跃度", "动作", "大小", "松手后落到任务栏", "置于最上层", "静音气泡", "只显示状态，不显示内容", "语言", "开机自启（v1.0）", "关于", "退出"]
    assert not find_action(menu, "开机自启（v1.0）").isEnabled()
    sizes = find_action(menu, "大小").menu().actions()
    assert [a.text() for a in sizes] == ["160", "200", "260", "320"]
    assert [a.isChecked() for a in sizes] == [False, True, False, False]


def test_menu_good_feedback_shows_proud(env):
    menu = env.ctl.build_menu()  # 要留着引用，菜单被回收后动作也没了
    find_action(find_action(menu, "工作遥控").menu(), "做得好").trigger()
    assert env.win.sprite_name == "proud"
    assert env.data.affection == 3
    assert env.data.feedback_queue == [{"kind": "good", "text": ""}]
    assert env.said == ["收到！下次干活时我就转告～"]


def test_menu_size_changes_window_and_save_and_checkmark(env):
    env.win.place_default()
    old_h = env.win.height()
    menu = env.ctl.build_menu()
    find_action(find_action(menu, "大小").menu(), "260").trigger()
    assert env.win.sprite_size[1] == 260
    assert env.win.height() > old_h
    assert env.data.window["height"] == 260
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
    assert "今天被摸 3 次" in text and "已完成 0 个任务" in text and "好感度 3" in text


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
    e1.ctl.set_size(160)
    e1.ctl.quit()
    e1.close()
    e2 = Env(tmp_path)
    try:
        assert e2.win.sprite_size[1] == 160
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


def test_click_wakes_sleeping_pet_with_wake_line(env):
    env.advance(16 * 60)
    assert env.win.sprite_name == "sleep"
    env.win.clicked.emit()
    assert env.win.sprite_name != "sleep"
    assert env.said and env.said[-1] in Lines()._lines["wake"]


def test_neglect_return_line_after_long_absence(env):
    env.advance(2 * 3600 + 60)
    env.win.clicked.emit()
    assert env.said[0] in Lines()._lines["neglect_return"]


class FakeBubble:
    """记录控制器对气泡的调用。"""

    def __init__(self):
        self.calls = []
        self.visible = False

    def windowFlags(self):
        return Qt.WindowStaysOnTopHint

    def isVisible(self):
        return self.visible

    def follow(self, body):
        self.calls.append(("follow", body))

    def say(self, text):
        self.calls.append(("say", text))
        self.visible = True

    def dismiss(self):
        self.calls.append(("dismiss",))
        self.visible = False


def make_with_bubble(tmp_path):
    e = Env(tmp_path)
    fb = FakeBubble()
    e.ctl = PetController(
        e.win, e.state, e.scheduler, lines=Lines(), overlay=e.overlay, bubble=fb,
        now_fn=lambda: e.now, autostart=False,
    )
    return e, fb


def test_default_say_goes_to_bubble_after_following_body(qapp, tmp_path):
    e, fb = make_with_bubble(tmp_path)
    try:
        e.win.clicked.emit()
        kinds = [c[0] for c in fb.calls]
        assert kinds[:2] == ["follow", "say"]
        assert fb.calls[0][1] == e.win.body_rect()
        assert fb.calls[1][1] in Lines()._lines["poke"]
    finally:
        e.close()


def test_muting_dismisses_visible_bubble_and_blocks_new_lines(qapp, tmp_path):
    e, fb = make_with_bubble(tmp_path)
    try:
        e.win.clicked.emit()
        assert fb.visible
        e.ctl.set_muted(True)
        assert ("dismiss",) in fb.calls and not fb.visible
        n = len(fb.calls)
        e.win.clicked.emit()
        assert len(fb.calls) == n  # 静音后不再弹
    finally:
        e.close()


def test_window_move_makes_visible_bubble_follow(qapp, tmp_path):
    e, fb = make_with_bubble(tmp_path)
    try:
        e.win.show()  # 隐藏的窗口不会收到 move 事件
        e.win.place_default()
        e.win.clicked.emit()
        fb.calls.clear()
        e.win.move(e.win.x() - 50, e.win.y())
        assert fb.calls and fb.calls[-1] == ("follow", e.win.body_rect())
        fb.visible = False
        fb.calls.clear()
        e.win.move(e.win.x() - 50, e.win.y())
        assert fb.calls == []  # 没显示时不用跟
    finally:
        e.close()


# ---------------------------------------------------------------- 来自 Claude 的事件
def test_working_event_shows_working_then_times_out_to_idle(env):
    env.ctl.handle_event("working", None)
    assert env.win.sprite_name == "working"
    env.advance(60)
    assert env.win.sprite_name == "working"
    env.ctl.handle_event("working", None)  # 有新事件就续期
    env.advance(280)
    assert env.win.sprite_name == "working"
    env.advance(30)  # 距最后一次事件超过 5 分钟
    assert env.win.sprite_name == "idle"
    assert any(t in Lines()._lines["claude_working"] for t in env.said)


def test_stop_event_shows_done_counts_task_and_says_done_line(env):
    env.ctl.handle_event("working", None)
    env.said.clear()
    env.ctl.handle_event("stop", None)
    assert env.win.sprite_name == "done"
    assert env.data.stats["claude_tasks"] == 1
    assert env.said[-1] in Lines()._lines["claude_done"]
    env.advance(3.5)
    assert env.win.sprite_name == "idle"


def test_session_start_and_notification_say_their_lines(env):
    env.ctl.handle_event("session_start", None)
    assert env.said[-1] in Lines()._lines["greeting"]
    env.ctl.handle_event("notification", "等你确认")
    assert env.said[-1] in Lines()._lines["claude_waiting"]


def test_react_event_sets_temporary_expression(env):
    env.ctl.handle_event("react", "proud")
    assert env.win.sprite_name == "proud"
    env.advance(3.5)
    assert env.win.sprite_name == "idle"


def test_unknown_event_or_expression_is_ignored(env):
    env.ctl.handle_event("bogus", None)
    env.ctl.handle_event("react", "not_a_state")
    env.ctl.handle_event("react", None)
    assert env.win.sprite_name == "idle"
    assert env.said == []


def test_muted_events_still_change_state_but_say_nothing(env):
    env.ctl.set_muted(True)
    env.ctl.handle_event("stop", None)
    assert env.win.sprite_name == "done"
    assert env.said == []


def test_take_feedback_text_merges_goods_and_clears(env):
    for _ in range(3):
        env.ctl.feedback_good()
    env.ctl.feedback_bad("测试没过")
    env.ctl.feedback_bad("")
    text = env.ctl.take_feedback_text()
    assert text.splitlines() == [
        "[诗音] 用户觉得你刚才做得很好。",
        "[诗音] 用户认为刚才的改动有问题：测试没过。请重新检查。",
        "[诗音] 用户认为刚才的改动有问题。请重新检查。",
    ]
    assert env.ctl.take_feedback_text() == ""
    assert env.data.feedback_queue == []


# ---------------------------------------------------------------- 审查修复
def test_quit_still_emits_when_saving_fails(qapp, tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    e = Env(tmp_path)
    try:
        e.scheduler.path = blocker / "state.json"  # 写盘必然失败
        e.win.patted.emit()
        got = []
        e.ctl.quit_requested.connect(lambda: got.append(1))
        e.ctl.quit()
        assert got == [1]
        assert e.scheduler.dirty  # 没写成，但没有崩
    finally:
        e.close()


MAIN = (0, 0, 1920, 1040)
RIGHT = (1920, 0, 1920, 1040)
UPPER = (0, -1080, 1920, 1040)  # 竖排：副屏在主屏上方


def test_pick_screen_rect_side_by_side():
    rects = [MAIN, RIGHT]
    assert pick_screen_rect(rects, 2500, 900, 248, 254) == RIGHT  # 存档在右边那块屏上
    assert pick_screen_rect(rects, 300, 900, 248, 254) == MAIN


def test_pick_screen_rect_stacked_uses_y_to_choose():
    rects = [MAIN, UPPER]
    # 同样的 x，靠 y 区分是主屏还是上方的屏
    assert pick_screen_rect(rects, 300, 800, 248, 254) == MAIN
    assert pick_screen_rect(rects, 300, -300, 248, 254) == UPPER
    # 旧存档没有 y：按 x 找到第一块
    assert pick_screen_rect(rects, 300, None, 248, 254) == MAIN


def test_pick_screen_rect_no_match_returns_none():
    assert pick_screen_rect([MAIN], 5000, 900, 248, 254) is None  # 副屏被拔了
    assert pick_screen_rect([], 100, 100, 248, 254) is None


def test_place_on_secondary_screen_feet_on_its_floor(env):
    env.win.place_on(RIGHT, 2500)
    from shion.pet_window import MARGIN_BOTTOM

    assert env.win.x() == 2500
    assert env.win.y() + env.win.height() - MARGIN_BOTTOM == RIGHT[1] + RIGHT[3]
    env.win.place_on(RIGHT, 99999)  # x 被夹进这块屏
    assert env.win.x() + env.win.width() - 64 <= RIGHT[0] + RIGHT[2]
    env.win.place_on(UPPER, 100)  # 竖排的上方屏：y 为负也正确
    assert env.win.y() + env.win.height() - MARGIN_BOTTOM == UPPER[1] + UPPER[3]


def test_restore_position_picks_saved_screen_via_fake_rects(env, monkeypatch):
    monkeypatch.setattr(env.ctl, "_screen_rects", lambda: [MAIN, RIGHT])
    env.data.window["x"], env.data.window["y"] = 2500, 800
    env.ctl.restore_position()
    assert env.win.x() == 2500 and env.win.x() >= RIGHT[0]  # 留在副屏，没有跳回主屏
    env.data.window["x"], env.data.window["y"] = 9000, 800  # 存档的屏已不存在
    env.ctl.restore_position()
    avail = QGuiApplication.primaryScreen().availableGeometry()
    assert avail.left() <= env.win.x() <= avail.right()


def test_relocate_returns_to_default_when_window_is_off_all_screens(env):
    avail = QGuiApplication.primaryScreen().availableGeometry()
    env.win.move(avail.right() + 5000, avail.top())  # 副屏被拔：窗口还在不存在的屏幕上
    env.ctl.relocate()
    assert avail.left() <= env.win.x() <= avail.right()
    assert env.win.y() + env.win.height() - 6 == avail.bottom() + 1


def test_relocate_preserves_floating_position_when_taskbar_changes(env):
    avail = QGuiApplication.primaryScreen().availableGeometry()
    env.win.place_default()
    env.win.move(env.win.x(), env.win.y() - 80)  # 比如任务栏变矮后，窗口悬空了
    y = env.win.y()
    env.ctl.relocate()
    assert env.win.y() == y


def test_relocate_does_nothing_while_dragging_or_falling(env):
    avail = QGuiApplication.primaryScreen().availableGeometry()
    env.win.move(avail.left() + 50, avail.top())
    env.win.start_fall()
    y = env.win.y()
    env.ctl.relocate()
    assert env.win.y() == y


def test_language_menu_lists_scanned_languages_and_checks_current(env):
    menu = env.ctl.build_menu()
    langs = find_action(menu, "语言").menu().actions()
    codes = env.ctl.lines.available_languages()
    assert [a.text() for a in langs] == [n for _, n in codes]
    assert {"English", "日本語"} <= {a.text() for a in langs}
    assert [a.isChecked() for a in langs] == [c == "zh" for c, _ in codes]


def test_switch_language_applies_immediately_and_saves(env):
    menu = env.ctl.build_menu()
    find_action(find_action(menu, "语言").menu(), "English").trigger()
    assert env.data.language == "en"
    menu2 = env.ctl.build_menu()
    assert [a.text() for a in menu2.actions() if not a.isSeparator()][:4] == [
        "Talk", "Work remote", "Expression", "Activity",
    ]
    assert "Together for 0m" in env.ctl.status_text(T0)
    assert "Pats today: 0" in env.ctl.status_text(T0)
    assert env.said[-1] in env.ctl.lines._lines["time_noon"]  # 切语言也是真实菜单操作
    env.mono[0] += 10  # 让本次时段气泡自然结束，再验证普通台词语言
    env.ctl.say_key("poke")
    assert env.said[-1] in env.ctl.lines._lines["poke"]
    assert env.said[-1] not in Lines()._lines["poke"]  # 不是中文台词
    env.ctl.set_language("ja")
    assert env.data.language == "ja"
    assert "0分" in env.ctl.status_text(T0)


def test_language_survives_restart(qapp, tmp_path):
    e1 = Env(tmp_path)
    e1.ctl.set_language("ja")
    e1.ctl.quit()
    e1.close()
    e2 = Env(tmp_path)
    try:
        assert e2.data.language == "ja"
    finally:
        e2.close()


def test_switch_language_dismisses_bubble_and_sets_fonts(env):
    class FakeBubble:
        def __init__(self):
            self.dismissed = 0
            self.fallback = None

        def dismiss(self):
            self.dismissed += 1

        def set_font_fallback(self, fams):
            self.fallback = list(fams)

    fb = env.ctl.bubble = FakeBubble()
    env.ctl.set_language("ja")
    assert fb.dismissed == 1
    assert fb.fallback == env.ctl.lines.font_fallback and fb.fallback


# ---- v0.2.1 状态感知 ----

def work(tool, target=""):
    import json
    return json.dumps({"tool": tool, "target": target}, ensure_ascii=False)


def test_working_detail_says_what_claude_is_doing(env):
    env.ctl.handle_event("working", work("read", "state.py"))
    assert env.said == ["在读 state.py……"]
    assert env.win.sprite_name == "working"


def test_working_activity_obeys_low_category_cooldown(env):
    env.ctl.handle_event("working", work("read", "state.py"))
    env.advance(1)
    env.ctl.handle_event("working", work("read", "state.py"))
    assert env.said == ["在读 state.py……"]
    env.advance(3)
    env.ctl.handle_event("working", work("read", "state.py"))
    assert env.said == ["在读 state.py……"] * 2
    env.ctl.handle_event("working", work("edit", "a.py"))
    assert env.said == ["在读 state.py……"] * 2
    env.advance(4)
    env.ctl.handle_event("working", work("edit", "a.py"))
    assert env.said[-1] == "在改 a.py……"


def test_working_without_detail_keeps_old_line(env):
    env.ctl.handle_event("working", None)
    assert len(env.said) == 1 and env.said[0] in env.ctl.lines._lines["claude_working"]


def test_privacy_mode_hides_target_and_summary(env):
    env.state.mark_time_speech_spoken("time_noon", env.now)  # 单独验证隐私路径
    env.ctl.set_privacy(True)
    assert env.data.privacy_mode is True
    env.ctl.handle_event("working", work("read", "secret.py"))
    env.ctl.handle_event("stop", "我把密码改好了")
    assert env.said[0] == "在忙……"
    assert not any("secret" in t or "密码" in t for t in env.said)
    env.ctl._show_status()
    assert not any("secret" in t or "密码" in t for t in env.said)


def test_stop_ignores_legacy_reply_in_bubble_log_and_status(env, caplog):
    import logging
    caplog.set_level(logging.INFO, logger="shion.controller")
    env.ctl.handle_event("stop", "改好了三个文件")
    assert len(env.said) == 1 and env.said[0] in env.ctl.lines._lines["claude_done"]
    assert env.win.sprite_name == "done"
    assert env.ctl.activity.recent()[0].target == ""
    env.advance(10)
    env.ctl._show_status()
    assert "改好了三个文件" not in "\n".join(env.said) + caplog.text


def test_stop_without_summary_uses_random_line(env):
    env.ctl.handle_event("stop", None)
    assert env.said and not env.said[0].startswith("做完啦：")


def test_muted_suppresses_activity_and_summary(env):
    env.ctl.set_muted(True)
    env.ctl.handle_event("working", work("bash"))
    env.ctl.handle_event("stop", "好了")
    assert env.said == []


def test_tool_error_makes_dizzy_2s(env):
    env.ctl.handle_event("tool_error", "Bash")
    assert env.win.sprite_name == "dizzy"
    assert len(env.said) == 1
    env.advance(2.1)
    assert env.win.sprite_name != "dizzy"


def test_double_click_status_lists_recent_activity(env):
    env.ctl.handle_event("session_start", None)
    env.ctl.handle_event("working", work("edit", "bubble.py"))
    env.ctl.handle_event("stop", "好了")
    env.said.clear()
    env.advance(10)  # 中优先级的状态查询要等完成提示结束。
    env.ctl._show_status()
    text = env.said[0]
    assert "最近：" in text
    assert "12:00 在改 bubble.py……" in text and "12:00 做完了" in text
    assert text.index("做完了") < text.index("在改")  # 新的在前


def test_nudge_bounces_and_speaks(env):
    env.ctl.handle_event("stop", None)
    env.said.clear()
    bounced = []
    env.win.bounce = lambda: bounced.append(1)
    env.advance(301)
    assert bounced == [1] and len(env.said) == 1


def test_menu_privacy_toggle_saves(env):
    menu = env.ctl.build_menu()
    act = find_action(menu, "只显示状态，不显示内容")
    assert act.isCheckable() and not act.isChecked()
    act.trigger()
    assert env.data.privacy_mode is True


def test_wake_line_not_overwritten_by_activity(env):
    env.advance(16 * 60)  # 睡着
    env.said.clear()
    env.ctl.handle_event("working", work("read", "a.py"))
    assert len(env.said) == 1 and "a.py" not in env.said[0]


def test_privacy_toggle_clears_recent_activity(env):
    env.ctl.set_privacy(True)
    env.ctl.handle_event("working", work("read", "secret.py"))
    env.ctl.set_privacy(False)
    env.said.clear()
    env.ctl._show_status()
    assert "secret" not in env.said[0]
