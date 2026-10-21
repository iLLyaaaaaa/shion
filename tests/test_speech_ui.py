"""走真实控制器出话路径，检查冷却不影响表情、好感度和统计。"""
import pytest

from shion.speech import Priority
from tests.test_controller import env, qapp, work


@pytest.mark.parametrize("event,detail,key", [
    ("stop", None, "claude_done"), ("tool_error", "Bash", "tool_error"),
    ("notification", None, "claude_waiting"),
    ("plan_ready", None, "plan_ready"),
])
def test_critical_event_interrupts_pat_and_blocks_new_low_and_medium_lines(env, event, detail, key):
    env.win.patted.emit()
    env.ctl.handle_event(event, detail)
    assert env.said[-1] in env.ctl.lines._lines[key]
    accepted = list(env.said)
    env.win.clicked.emit()
    env.ctl.feedback_good()
    env.ctl._show_status()
    env.ctl.handle_event("working", work("read", "a.py"))
    assert env.said == accepted
    assert env.data.affection == 4 and len(env.data.feedback_queue) == 1


def test_medium_menu_speech_interrupts_low_but_not_other_medium(env):
    env.win.clicked.emit()
    env.ctl.feedback_good()
    assert env.said[-1] in env.ctl.lines._lines["praise_menu"]
    before = len(env.said)
    env.ctl.handle_event("session_start")
    env.ctl.feedback_good()
    assert len(env.said) == before and len(env.data.feedback_queue) == 2


def test_continuous_pat_says_twice_without_reducing_hearts_or_stats(env, monkeypatch):
    env.state.mark_time_speech_spoken("time_noon", env.now)  # 单独验证原交互的台词/冷却
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
    env.state.mark_time_speech_spoken("time_noon", env.now)  # 单独验证原交互的台词/冷却
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
    env.state.mark_time_speech_spoken("time_noon", env.now)  # 单独验证原交互的台词/冷却
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


@pytest.mark.parametrize("event,key", [("stop", "claude_done"), ("plan_ready", "plan_ready")])
def test_ready_reminder_overrides_wake_and_is_high(env, event, key):
    env.advance(901)
    env.ctl.handle_event(event, "私密内容")
    reminder = env.said[-1]
    assert reminder in env.ctl.lines._lines[key]
    env.win.patted.emit()
    assert env.said[-1] == reminder


def test_nudge_can_interrupt_current_high(env):
    env.ctl.handle_event("stop")
    env.advance(299)
    env.ctl.say_key("tool_error")  # 只显示高优先级台词，不用新事件取消原有催促。
    env.advance(1)
    assert env.said[-1] in env.ctl.lines._lines["nudge"]


@pytest.mark.parametrize("lang,text", [
    ("zh", "计划写好啦，去看看吧～"),
    ("en", "The plan's ready! Take a look~"),
    ("ja", "計画ができたよ、見てみてね～"),
])
@pytest.mark.parametrize("muted", [False, True])
def test_plan_ready_jumps_once_even_when_muted_and_ignores_content(env, lang, text, muted, caplog):
    import logging
    caplog.set_level(logging.INFO, logger="shion.controller")
    env.ctl.set_language(lang)
    env.ctl.set_muted(muted)
    env.ctl.handle_event("working")
    env.said.clear()
    env.ctl.handle_event("plan_ready", "私密计划")
    assert env.said == ([] if muted else [text])
    assert env.win.motion_active and env.win.displayed_sprite == "jump_1"
    assert not env.win.idle_motion_active  # 安静档/固定表情也不会取消事件小跳
    assert not env.state.is_working(env.now)
    assert env.data.stats["claude_tasks"] == 0
    assert len(env.ctl.activity) == 1  # 只有先前的 working，不存计划
    assert "私密计划" not in caplog.text
    pos = env.win.pos()
    env.advance(0.35)
    assert env.win.displayed_sprite == "jump_3" and env.win._jump_offset == pytest.approx(45)
    assert env.win.pos() == pos
    env.advance(0.5)
    assert not env.win.motion_active and env.win._jump_offset == 0


@pytest.mark.parametrize("lang", ["zh", "en", "ja"])
@pytest.mark.parametrize("private", [False, True])
def test_stop_reminders_always_ignore_content_and_keep_done_state_and_count(env, lang, private):
    env.ctl.set_language(lang)
    env.ctl.set_privacy(private)
    env.ctl.handle_event("working")
    env.said.clear()
    env.ctl.handle_event("stop", "私密回复")
    assert len(env.said) == 1 and env.said[0] in env.ctl.lines._lines["claude_done"]
    assert env.ctl._speech.priority == Priority.HIGH
    assert env.win.sprite_name == "done" and not env.state.is_working(env.now)
    assert env.data.stats["claude_tasks"] == 1
    env.advance(10)
    env.ctl._show_status()
    assert "私密回复" not in "\n".join(env.said)


def test_plan_ready_interrupts_high_bubble_without_creating_a_permission_panel(env):
    env.ctl.say_key("tool_error")
    env.ctl.handle_event("plan_ready")
    env.ctl.tick()
    assert env.said[-1] == "计划写好啦，去看看吧～"
    assert env.ctl._speech.priority == Priority.HIGH
    assert env.ctl._perm_panel is None and env.ctl.hub.permissions.pending() == []


@pytest.mark.parametrize("mode", ["quiet", "fixed"])
def test_plan_jump_survives_calm_sync(env, mode):
    if mode == "quiet":
        env.data.activity_level = "quiet"
    else:
        env.data.fixed_expression = "proud"
    env.ctl.handle_event("plan_ready")
    env.advance(0.35)
    assert env.win.motion_active and env.win._jump_offset == pytest.approx(45)
    env.advance(0.5)
    assert env.win.sprite_name == ("proud" if mode == "fixed" else "idle")


def test_mute_and_language_dismiss_current_priority_but_keep_low_cooldown(env):
    env.state.mark_time_speech_spoken("time_noon", env.now)  # 单独验证原交互的台词/冷却
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
    monkeypatch.setattr(env.ctl.lines, "pick", lambda key, level=None: picked.append(key) or "新台词")
    assert not env.ctl.say_key("poke") and not picked
    env.advance(10)
    assert env.ctl.say_key("poke") and picked == ["poke"]
