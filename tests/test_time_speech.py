"""时段问候：本地假时钟、真实气泡仲裁和临时存档。"""
from datetime import datetime, timedelta

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtTest import QTest

from shion.lines import Lines
from shion.speech import Priority
from shion.state import PetState, SaveData, load, save, time_speech_period
from tests.test_controller import Env, T0, qapp


@pytest.mark.parametrize("clock,key", [
    ("00:00:00", "late"), ("01:59:59", "late"), ("02:00:00", "dawn"),
    ("04:59:59", "dawn"), ("05:00:00", "morning"), ("09:59:59", "morning"),
    ("10:00:00", None), ("11:29:59", None), ("11:30:00", "noon"),
    ("13:29:59", "noon"), ("13:30:00", None), ("17:29:59", None),
    ("17:30:00", "evening"), ("19:29:59", "evening"), ("19:30:00", None),
    ("22:59:59", None), ("23:00:00", "late"), ("23:59:59", "late"),
])
def test_local_time_boundaries(clock, key):
    now = datetime.fromisoformat(f"2026-10-21T{clock}")
    assert time_speech_period(now) == (f"time_{key}" if key else None)


def test_query_is_read_only_and_midnight_resets_even_within_late(tmp_path):
    now = datetime(2026, 10, 21, 23, 59, 59)
    state = PetState(SaveData(), now)
    state.interact(now)
    before = state.save.to_dict()
    assert state.pending_time_speech(now) == "time_late"
    assert state.pending_time_speech(now) == "time_late"
    assert state.save.to_dict() == before
    state.mark_time_speech_spoken("time_late", now)
    assert state.pending_time_speech(now) is None
    path = tmp_path / "state.json"
    save(path, state.save)
    restarted = PetState(load(path), now)
    restarted.interact(now)
    assert restarted.pending_time_speech(now) is None
    tomorrow = now + timedelta(seconds=1)
    restarted.interact(tomorrow)
    assert restarted.save.time_speech == {"date": "2026-10-22", "spoken": []}
    assert restarted.pending_time_speech(tomorrow) == "time_late"
    restarted.mark_time_speech_spoken("time_late", tomorrow)
    assert restarted.pending_time_speech(tomorrow) is None


def test_each_period_has_its_own_daily_record_and_tick_rolls_date():
    state = PetState(SaveData(), T0)
    for hour, minute, key in [(5, 0, "morning"), (11, 30, "noon"),
                              (17, 30, "evening"), (23, 0, "late")]:
        now = T0.replace(hour=hour, minute=minute)
        state.interact(now)
        assert state.pending_time_speech(now) == f"time_{key}"
        state.mark_time_speech_spoken(f"time_{key}", now)
        assert state.pending_time_speech(now) is None
    state.tick(T0 + timedelta(days=1))
    assert state.save.time_speech == {"date": "2026-10-20", "spoken": []}


@pytest.mark.parametrize("raw", [None, [], True, {}, {"date": 1},
    {"date": "bad", "spoken": []}, {"date": "2026-02-30", "spoken": []},
    {"date": "2026-10-21", "spoken": "time_noon"}])
def test_invalid_or_missing_save_field_is_safe(raw):
    data = SaveData.from_dict({"schema_version": 5, "affection": 42, "time_speech": raw})
    assert data.time_speech == {"date": "", "spoken": []}
    assert data.affection == 42 and data.schema_version == 5


def test_save_filters_unknown_keys_duplicates_and_copies_list():
    data = SaveData.from_dict({"time_speech": {"date": "2026-10-21",
        "spoken": ["time_noon", "time_noon", "bad", 1, {}, "time_dawn"]}})
    assert data.time_speech["spoken"] == ["time_dawn", "time_noon"]
    exported = data.to_dict()
    exported["time_speech"]["spoken"].clear()
    assert data.time_speech["spoken"] == ["time_dawn", "time_noon"]


@pytest.fixture
def env(qapp, tmp_path):
    instance = Env(tmp_path)
    instance.data.activity_level = "quiet"
    yield instance
    instance.close()


def test_success_marks_dirty_persists_and_language_does_not_rearm(env):
    env.scheduler.flush(env.now)
    assert env.ctl._try_time_speech()
    assert env.said[-1] in Lines()._lines["time_noon"]
    assert env.scheduler.dirty
    env.scheduler.flush(env.now)
    assert load(env.path).time_speech["spoken"] == ["time_noon"]
    env.ctl.set_language("ja")
    assert not env.ctl._try_time_speech()
    assert len(env.said) == 1


@pytest.mark.parametrize("blocker", ["work", "mute", "sleep", "fixed_sleep", "high", "medium", "low"])
def test_blocked_does_not_pick_or_consume_then_retries(env, monkeypatch, blocker):
    if blocker == "work":
        env.state.claude_event("prompt", None, env.now)
        env.state.select_expression("happy", env.now)  # 表情不能掩盖工作会话
    elif blocker == "mute":
        env.data.bubble_muted = True
    elif blocker == "sleep":
        env.state.menu_talk(env.now, sleep=True)
    elif blocker == "fixed_sleep":
        env.data.fixed_expression = "sleep"
    else:
        env.ctl.say("busy", priority={"high": Priority.HIGH, "medium": Priority.MEDIUM,
                                      "low": Priority.LOW}[blocker])
    with monkeypatch.context() as patch:
        def unexpected(*args, **kwargs):
            pytest.fail("被挡住时不应抽取台词")
        patch.setattr(env.ctl.lines, "pick_for_level", unexpected)
        patch.setattr(env.ctl.lines, "pick", unexpected)
        assert not env.ctl._try_time_speech()
    assert env.data.time_speech["spoken"] == []
    env.state.end_session(None)
    env.data.bubble_muted = False
    env.data.fixed_expression = None
    env.state.interact(env.now)
    env.mono[0] += 10
    env.ctl._speech.dismiss()
    assert env.ctl._try_time_speech()
    assert env.data.time_speech["spoken"] == ["time_noon"]


def test_original_responses_win_and_tick_does_not_replay(env):
    env.ctl.greet_startup(False)
    assert env.said[-1] in env.ctl.lines._lines["startup"]
    assert env.data.time_speech["spoken"] == []
    env.advance(10)
    assert len(env.said) == 1  # 安静档，没有闲聊机会；气泡消失不自动补播
    env.ctl._on_gesture("belly")  # 无回应的实际交互提供新机会
    assert env.said[-1] in env.ctl.lines._lines["time_noon"]


def test_wake_and_interaction_lines_win(env):
    env.state.menu_talk(env.now, sleep=True)
    env.ctl._on_click()
    assert env.said[-1] in env.ctl.lines._lines["wake"]
    assert env.data.time_speech["spoken"] == []
    env.advance(10)
    env.ctl._on_click()
    assert env.said[-1] in env.ctl.lines._lines["poke"]
    assert env.data.time_speech["spoken"] == []


def test_idle_opportunity_uses_time_once_then_ordinary_idle(env, monkeypatch):
    monkeypatch.setattr(env.ctl._idle, "step", lambda *args: "talk")
    env.ctl.tick()
    assert len(env.said) == 1 and env.said[-1] in env.ctl.lines._lines["time_noon"]
    env.advance(10)
    assert len(env.said) == 2 and env.said[-1] in env.ctl.lines._lines["idle_talk"]


def test_expired_period_not_replayed_and_work_events_are_not_opportunities(env):
    env.ctl.handle_event("prompt")
    env.ctl.handle_event("stop")
    assert env.data.time_speech["spoken"] == []
    env.now = env.now.replace(hour=14)
    env.mono[0] += 7200
    env.ctl._speech.dismiss()
    env.ctl._on_gesture("belly")
    assert env.data.time_speech["spoken"] == []


def test_hover_and_cancelled_menu_do_not_trigger(env, monkeypatch):
    env.win.show()
    QTest.mouseMove(env.win, QPoint(60, 100))
    menu = env.ctl.build_menu()
    monkeypatch.setattr(env.ctl, "build_menu", lambda: menu)
    monkeypatch.setattr(menu, "exec", lambda *_: None)
    env.ctl.show_menu(QPoint(0, 0))
    assert not env.said and env.data.time_speech["spoken"] == []


def test_missing_time_pool_does_not_mark_spoken(env):
    env.ctl.lines._lines.pop("time_noon")
    assert not env.ctl._try_time_speech()
    assert env.data.time_speech["spoken"] == []
