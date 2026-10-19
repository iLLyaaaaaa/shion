"""走真实控制器出话路径，检查冷却不影响表情、好感度和统计。"""
import pytest

from shion.speech import Priority
from tests.test_controller import env, qapp, work


@pytest.mark.parametrize("event,detail,key", [
    ("stop", None, "claude_done"), ("tool_error", "Bash", "tool_error"),
    ("notification", None, "claude_waiting"),
])
def test_critical_event_interrupts_pat_and_blocks_new_low_and_medium_lines(env, event, detail, key):
    env.win.patted.emit()
    env.ctl.handle_event(event, detail)
    assert env.said[-1] in env.ctl.lines._lines[key]
    accepted = list(env.said)
    env.win.clicked.emit()
    env.ctl.praise()
    env.ctl._show_status()
    env.ctl.handle_event("working", work("read", "a.py"))
    assert env.said == accepted
    assert env.data.affection == 4 and env.data.pending_praise == 1


def test_medium_menu_speech_interrupts_low_but_not_other_medium(env):
    env.win.clicked.emit()
    env.ctl.praise()
    assert env.said[-1] in env.ctl.lines._lines["praise_menu"]
    before = len(env.said)
    env.ctl.handle_event("session_start")
    env.ctl.praise()
    assert len(env.said) == before and env.data.pending_praise == 2


def test_continuous_pat_says_twice_without_reducing_hearts_or_stats(env, monkeypatch):
    env.data.activity_level = "quiet"
    bursts = []
    original = env.overlay.burst
    def burst(point, **kwargs):
        bursts.append(kwargs.get("start_session", False))
        original(point, **kwargs)
    monkeypatch.setattr(env.overlay, "burst", burst)
    env.win.patted.emit()
    for _ in range(12):
        env.advance(0.5)
        env.win.patted.emit()
    assert len(env.said) == 1  # 恰好 6 秒还不重说。
    env.advance(0.001)
    env.win.patted.emit()
    assert len(env.said) == 2
    for _ in range(16):
        env.advance(0.5)
        env.win.patted.emit()
    assert len(env.said) == 2 and len(bursts) == 30
    assert bursts == [True] + [False] * 29  # 六秒后的第二句不算新摸头过程
    assert env.data.affection == env.data.stats["pats"] == 30
    assert env.win.sprite_name == "happy"
    assert len(env.overlay.particles.items(env.mono[0])) <= 6


def test_blocked_pat_is_dropped_without_retry_before_six_seconds(env):
    env.ctl.handle_event("stop", "好了")
    accepted = list(env.said)
    env.win.patted.emit()
    for _ in range(12):
        env.advance(0.5)
        env.win.patted.emit()
    assert env.said == accepted  # 完成提示已结束，也不补播被拦截的开头那句。
    env.advance(0.001)
    env.win.patted.emit()
    assert env.said[-1] in env.ctl.lines._lines["pat"] and len(env.said) == 2


def test_poke_variants_and_shaken_drag_use_source_cooldowns(env, monkeypatch):
    monkeypatch.setattr(env.state._rng, "random", lambda: 0)
    for _ in range(3):
        env.win.clicked.emit()
        env.advance(0.1)
    assert env.win.sprite_name == "stop" and len(env.said) == 1
    env.advance(4)
    env.win.drag_started.emit()
    assert env.said[-1] in env.ctl.lines._lines["drag"]
    accepted = list(env.said)
    env.advance(2.5)
    env.win._shake.shaken = True
    env.win.drag_finished.emit()
    assert env.win.sprite_name == "dizzy" and env.said == accepted


def test_stop_summary_always_overrides_wake_and_is_high(env):
    env.advance(901)
    env.ctl.handle_event("stop", "改好了")
    assert env.said[-1] == "做完啦：改好了"
    env.win.patted.emit()
    assert env.said[-1] == "做完啦：改好了"


def test_nudge_can_interrupt_current_high(env):
    env.ctl.handle_event("stop")
    env.advance(299)
    env.ctl.say_key("tool_error")  # 只显示高优先级台词，不用新事件取消原有催促。
    env.advance(1)
    assert env.said[-1] in env.ctl.lines._lines["nudge"]


def test_mute_and_language_dismiss_current_priority_but_keep_low_cooldown(env):
    env.ctl.handle_event("stop")
    env.ctl.set_muted(True)
    env.ctl.set_muted(False)
    env.win.patted.emit()
    assert env.said[-1] in env.ctl.lines._lines["pat"]
    env.ctl.set_language("en")
    assert not env.ctl.say_key("pat")
    assert env.ctl.say_key("poke")
    assert env.said[-1] in env.ctl.lines._lines["poke"]


def test_status_keeps_mute_exemption_and_respects_priority(env):
    env.ctl.set_muted(True)
    env.ctl._show_status()
    assert "好感度" in env.said[-1]
    env.ctl.say("授权请求", priority=Priority.HIGH, category="permission_request")
    env.ctl._show_status()
    assert env.said[-1] == "授权请求"


def test_suppressed_category_does_not_consume_random_line_selection(env, monkeypatch):
    env.ctl.handle_event("stop")
    picked = []
    monkeypatch.setattr(env.ctl.lines, "pick", lambda key: picked.append(key) or "新台词")
    assert not env.ctl.say_key("poke") and not picked
    env.advance(10)
    assert env.ctl.say_key("poke") and picked == ["poke"]
