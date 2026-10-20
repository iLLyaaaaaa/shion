"""对话内容、结算、睡眠与真实 Qt 控件路径（假时钟）。"""
import json
import random
from datetime import datetime, timedelta

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QPushButton, QLineEdit

from shion.effects import Crumbs
from shion.menu_content import MenuContent, localized
from shion.state import PetState, SaveData, load, save
from shion.speech import Priority
from tests.test_controller import Env, env, find_action, qapp, T0


def test_builtin_content_has_four_items_and_complete_three_language_responses():
    content = MenuContent()
    for kind in ("snacks", "talks"):
        items = getattr(content, kind)
        assert len(items) == 4 and len({i.id for i in items}) == 4
        for item in items:
            assert set(item.name) == {"zh", "en", "ja"}
            assert 2 <= len(item.responses) <= 3
            for response in item.responses:
                assert set(response.text) == {"zh", "en", "ja"}
                assert all("claude" not in s.lower() for s in [*item.name.values(), *response.text.values()])
    assert content.full["zh"] == "撑、撑不下了……"
    assert content.find("talks", "goodnight").action == "sleep"


def test_random_responses_never_repeat_and_missing_language_uses_chinese():
    content = MenuContent(rng=random.Random(12))
    item = content.snacks[0]
    texts = [localized(content.pick("snacks", item, "en").text, "en") for _ in range(30)]
    assert all(a != b for a, b in zip(texts, texts[1:]))
    assert localized(item.name, "missing") == item.name["zh"]


@pytest.mark.parametrize("bad", [None, [], {}, {"schema_version": 2}, {"schema_version": True}, {"schema_version": 1, "items": 3}])
def test_bad_files_are_disabled_without_crashing(tmp_path, bad):
    (tmp_path / "talks.json").write_text(json.dumps(bad), encoding="utf-8")
    content = MenuContent(tmp_path)
    assert not content.snacks and not content.talks


@pytest.mark.parametrize("changes", [
    {"action": "run_python"}, {"action": []}, {"name": {}}, {"id": []},
    {"responses": [{"text": {"zh": "坏"}, "expression": "drag"}]},
    {"responses": [{"text": {"zh": "坏"}, "expression": []}]}, {"responses": []},
])
def test_bad_item_is_skipped_while_valid_data_still_loads(tmp_path, changes):
    valid = {"id": "custom", "name": {"zh": "测试"}, "responses": [{"text": {"zh": "回应"}}]}
    bad = {**valid, "id": "bad", **changes}
    raw = {"schema_version": 1, "items": [bad, valid, valid]}
    (tmp_path / "talks.json").write_text(json.dumps(raw), encoding="utf-8")
    content = MenuContent(tmp_path)
    assert [i.id for i in content.talks] == ["custom"]
    assert localized(content.talks[0].responses[0].text, "ja") == "回应"


def test_snacks_complete_once_and_share_five_item_daily_limit(env):
    env.data.activity_level = "quiet"
    for i in range(5):
        ident = env.ctl.menu_content.snacks[i % 4].id
        env.ctl.choose_dialogue("snacks", ident)
        assert env.state.eating and env.win.sprite_name == "happy"
        assert env.data.affection == i * 2
        env.ctl.choose_dialogue("snacks", ident)  # 连按不能产生第二次喂食
        env.advance(1.999)
        assert env.data.affection == i * 2
        env.advance(0.001)
        assert not env.state.eating and env.data.affection == (i + 1) * 2
        env.advance(10)
        assert env.data.affection == (i + 1) * 2
    env.ctl.choose_dialogue("snacks", "cookie")
    assert not env.state.eating
    assert env.data.snacks == {"date": T0.date().isoformat(), "count": 5}
    assert env.said[-1] == "撑、撑不下了……"
    assert env.data.stats["pats"] == 0 and env.data.feedback_queue == []


def test_snack_count_survives_restart_and_resets_next_day(env, tmp_path):
    env.data.snacks["count"] = 4
    env.ctl.choose_dialogue("snacks", "pudding")
    env.advance(2)
    env.scheduler.flush()
    again = Env(tmp_path)
    try:
        again.ctl.choose_dialogue("snacks", "milk_tea")
        assert not again.state.eating and again.data.affection == 2
        again.advance(86400)
        again.ctl.choose_dialogue("snacks", "milk_tea")
        assert again.state.eating
        again.advance(2)
        assert again.data.snacks["count"] == 1 and again.data.affection == 4
    finally:
        again.close()


def test_midnight_feed_is_counted_on_completion_date():
    now = datetime(2026, 10, 19, 23, 59, 59)
    state = PetState(SaveData(), now)
    assert state.start_snack(now)
    state.tick(now + timedelta(seconds=2))
    assert state.save.snacks == {"date": "2026-10-20", "count": 1}


def test_unfinished_feed_is_not_saved_or_awarded_on_quit(env):
    env.ctl.choose_dialogue("snacks", "cookie")
    env.advance(1)
    env.ctl.quit()
    assert not env.state.eating
    saved = load(env.path)
    assert saved.affection == 0 and saved.snacks["count"] == 0
    env.advance(10)
    assert env.data.affection == 0


def test_v3_migration_and_snack_validation(tmp_path):
    raw = {"schema_version": 3, "affection": 19, "stats": {"date": "2026-10-19", "pats": 8, "claude_tasks": 2},
           "feedback_queue": [{"kind": "good", "text": ""}]}
    data = SaveData.from_dict(raw)
    state = PetState(data, T0)
    assert data.schema_version == 4 and data.affection == 19 and data.stats["pats"] == 8
    assert data.feedback_queue and data.snacks["count"] == 0
    state.start_snack(T0)
    state.tick(T0 + timedelta(seconds=2))
    save(tmp_path / "state.json", data)
    assert load(tmp_path / "state.json") == data
    for value in (None, [], "bad", {"date": [], "count": True}, {"count": -2}):
        assert SaveData.from_dict({"snacks": value}).snacks["count"] == 0


@pytest.mark.parametrize("ident,expected", [("headpat", "happy"), ("well_done", "proud"), ("stay_with_me", "happy"), ("goodnight", "sleep")])
def test_preset_changes_expression_without_rewards(env, ident, expected):
    env.ctl.choose_dialogue("talks", ident)
    assert env.win.sprite_name == expected
    assert env.data.affection == 0 and env.data.stats["pats"] == 0 and not env.data.feedback_queue


@pytest.mark.parametrize("wake", ["interact", "pat", "click", "working", "prompt"])
def test_goodnight_persists_until_interaction_or_work_event(wake):
    state = PetState(SaveData(), T0)
    state.menu_talk(T0, sleep=True)
    state.tick(T0 + timedelta(seconds=30))
    assert state.current(T0 + timedelta(seconds=30)) == "sleep"
    later = T0 + timedelta(seconds=31)
    if wake in ("working", "prompt"):
        state.claude_event(wake, None, later)
    else:
        getattr(state, wake)(later)
    assert state.current(later) != "sleep"


@pytest.mark.parametrize("block,expected", [("fixed", "proud"), ("paused", "stop"), ("working", "working")])
def test_goodnight_preserves_higher_priority_state(env, block, expected):
    if block == "fixed":
        env.data.fixed_expression = "proud"
    elif block == "paused":
        env.state.paused = True
    else:
        env.ctl.handle_event("working")
    env.ctl.choose_dialogue("talks", "goodnight")
    assert env.win.sprite_name == expected
    env.data.fixed_expression = None
    env.state.paused = False
    env.advance(301)
    assert env.win.sprite_name == "sleep"


def test_muted_or_high_priority_speech_keeps_menu_behaviour(env):
    env.ctl.set_muted(True)
    env.ctl.choose_dialogue("talks", "goodnight")
    assert env.win.sprite_name == "sleep" and not env.said
    env.ctl.choose_dialogue("snacks", "cookie")
    env.advance(2)
    assert env.data.affection == 2 and not env.said
    env.ctl.set_muted(False)
    env.ctl.say("important", priority=Priority.HIGH)
    env.ctl.choose_dialogue("talks", "headpat")
    assert env.said == ["important"] and env.win.sprite_name == "happy"


def test_crumbs_are_bounded_fall_fade_and_do_not_replay_missed_emissions():
    crumbs = Crumbs(random.Random(3))
    crumbs.start(0)
    start = crumbs.items(0)
    later = crumbs.items(0.3)
    assert len(start) == len(later) == 3
    assert all(b[1] > a[1] and b[3] < a[3] for a, b in zip(start, later))
    for i in range(200):
        crumbs.update(i / 100)
        assert len(crumbs.items(i / 100)) <= crumbs.MAX
    crumbs.update(20)
    assert not crumbs.active
    crumbs.start(30)
    crumbs.update(31.5)
    assert len(crumbs.items(31.5)) == 3


def click_button(panel, text):
    button = next(b for b in panel.findChildren(QPushButton) if b.text() == text and not b.isHidden())
    QTest.mouseClick(button, Qt.LeftButton)


def test_menu_opens_without_keyboard_arming_and_click_enables_navigation(env, qapp):
    menu = env.ctl.build_menu()
    find_action(menu, "对话").trigger()
    panel = env.ctl._dialogue
    assert panel.isVisible() and not panel.keyboard_ready
    assert panel.testAttribute(Qt.WA_ShowWithoutActivating)
    QTest.keyClick(panel, Qt.Key_1)
    QTest.keyClick(panel, Qt.Key_Escape)
    assert panel.page == "talks" and panel.isVisible()
    QTest.mouseClick(panel, Qt.LeftButton, pos=QPoint(3, 3))
    qapp.processEvents()
    assert panel.keyboard_ready and panel.isActiveWindow()
    QTest.keyClick(panel, Qt.Key_1)
    assert panel.page == "snacks"
    QTest.keyClick(panel, Qt.Key_0)
    assert panel.page == "talks"
    QTest.keyClick(panel, Qt.Key_3)
    assert not panel.isVisible() and env.win.sprite_name == "sleep"


def test_focus_loss_disables_keyboard_until_another_click(env, qapp):
    env.ctl.open_dialogue()
    panel = env.ctl._dialogue
    QTest.mouseClick(panel, Qt.LeftButton, pos=QPoint(3, 3))
    qapp.processEvents()
    editor = QLineEdit()
    editor.show()
    editor.activateWindow()
    editor.setFocus()
    qapp.processEvents()
    qapp.processEvents()  # 运行失焦确认 timer
    QTest.keyClick(panel, Qt.Key_2)
    assert not panel.keyboard_ready and panel.isVisible() and env.data.affection == 0
    QTest.mouseClick(panel, Qt.LeftButton, pos=QPoint(3, 3))
    qapp.processEvents()
    QTest.keyClick(panel, Qt.Key_Escape)
    assert not panel.isVisible()
    editor.close()


def test_opening_keeps_other_window_focus_and_typing(env, qapp):
    if qapp.platformName() == "offscreen":
        pytest.skip("offscreen 插件不实现非激活显示；本项由原生 Windows 回归验证")
    editor = QLineEdit()
    try:
        editor.show()
        editor.activateWindow()
        editor.setFocus()
        qapp.processEvents()
        assert qapp.focusWidget() is editor
        env.ctl.open_dialogue()
        qapp.processEvents()
        assert qapp.focusWidget() is editor
        assert qapp.activeWindow() is editor
        QTest.keyClicks(editor, "123")
        assert editor.text() == "123" and env.ctl._dialogue.page == "talks"
    finally:
        editor.close()


def test_goodnight_clears_short_reaction_and_suppresses_idle_behaviour(env):
    env.ctl.choose_dialogue("talks", "well_done")
    env.ctl.choose_dialogue("talks", "goodnight")
    assert env.win.sprite_name == "sleep"
    env.advance(30)
    assert env.win.sprite_name == "sleep" and env.ctl._idle.next_at is None


def test_mouse_selection_busy_state_and_idle_pause(env):
    env.ctl.open_dialogue()
    panel = env.ctl._dialogue
    env.ctl.tick()
    assert env.ctl._idle.next_at is None
    click_button(panel, "1. 喂零食")
    click_button(panel, "1. 饼干")
    assert env.state.eating and not panel.isVisible()
    env.ctl.open_dialogue()
    assert panel.busy and 1 not in panel._choices
    env.advance(2)
    assert not panel.busy and 1 in panel._choices
    env.ctl._crumbs.tick()
    flags = env.ctl._crumbs.windowFlags()
    assert flags & Qt.WindowTransparentForInput and flags & Qt.WindowDoesNotAcceptFocus


def test_permission_request_closes_dialogue_and_blocks_reopening(env):
    env.ctl.open_dialogue()
    env.ctl.hub.permissions.open("Bash", "git status")
    env.ctl.tick()
    assert not env.ctl._dialogue.isVisible() and env.ctl._perm_panel.isVisible()
    env.ctl.open_dialogue()
    assert not env.ctl._dialogue.isVisible()


@pytest.mark.parametrize("lang", ["zh", "en", "ja"])
def test_language_switch_updates_visible_menu_and_keeps_panel_on_screen(env, lang):
    env.ctl.open_dialogue()
    env.ctl.set_language(lang)
    panel = env.ctl._dialogue
    labels = [w.text() for w in panel.findChildren(QLabel) if not w.isHidden()]
    assert "> " + env.ctl.lines.ui("menu_talk") in labels
    assert not any("claude" in s.lower() for s in labels)
    env.win.place_default()
    env.ctl._on_window_moved()
    assert panel.screen().availableGeometry().contains(panel.geometry())


def test_missing_content_is_reported_and_unknown_ids_do_nothing(env, tmp_path):
    env.ctl.menu_content = MenuContent(tmp_path)
    env.ctl.open_dialogue()
    panel = env.ctl._dialogue
    assert any(w.text() == "内容暂不可用" for w in panel.findChildren(QLabel))
    env.ctl.choose_dialogue("snacks", "missing")
    env.ctl.choose_dialogue("invalid", "headpat")
    assert not env.said and not env.state.eating


@pytest.mark.parametrize("kind", ["dialogue", "snacks", "eating"])
def test_new_snapshot_modes(qapp, tmp_path, kind):
    from shion.app import snapshot_panel
    from PySide6.QtGui import QImage
    out = tmp_path / f"{kind}.png"
    assert snapshot_panel(str(out), kind, lang="ja") == 0
    image = QImage(str(out))
    assert not image.isNull() and image.width() >= 200 and image.height() > 100
