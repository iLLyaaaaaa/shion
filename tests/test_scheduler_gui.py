"""Synthetic Qt integration; never a real Claude/Codex client acceptance test."""
from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QPushButton

from shion.chatgpt import ChatGPTConnection
from shion.events import Observation, ObserverHeartbeat
from shion.scheduler import Priority, SourceCapabilities
from shion.state import SaveData, load
from shion.tasks import TaskLedger
from tests.test_controller import Env, env, qapp  # noqa: F401


def event(kind="UserPromptSubmit", provider="chatgpt", session="s", turn="t", **kw):
    return Observation(kind, session, turn, provider=provider,
                       namespace="codex-local" if provider == "chatgpt" else "claude-test", **kw)


def enable(env, tmp_path):
    ctl = env.ctl
    ctl.chatgpt = ChatGPTConnection(tmp_path / "data", tmp_path / "codex")
    ctl.chatgpt.ledger = TaskLedger(clock=lambda: env.mono[0])
    ctl.set_v2_scheduler_enabled(True)
    return ctl


@pytest.mark.parametrize("provider", ["claude", "chatgpt"])
def test_single_task_animation_and_no_control_or_reward_side_effects(env, tmp_path, provider):
    ctl = enable(env, tmp_path)
    before = env.data.affection, dict(env.data.stats)
    e = event(provider=provider)
    ctl.observe_v2(e)
    ctl.tick()
    assert ctl.v2.display.priority == Priority.P4
    assert env.win.sprite_name == "working"
    assert ctl.v2.core.ledger is ctl.chatgpt.ledger
    assert not ctl.can_interrupt()
    ctl.observe_v2(replace(e, event="Stop"))
    ctl.tick()
    assert ctl.v2.display.priority == Priority.P3
    assert ctl.v2.display.result == "unknown"
    assert env.win.sprite_name != "done"
    assert before == (env.data.affection, env.data.stats)


@pytest.mark.parametrize("front", ["claude", "chatgpt"])
def test_verified_foreground_and_background_restore(env, tmp_path, front):
    ctl = enable(env, tmp_path)
    a, b = event(provider="claude"), event()
    for e in (a, b):
        ctl.observe_v2(e)
    target = a if front == "claude" else b
    ctl.v2.core.set_foreground(target.key, verified=True)
    env.advance(1.1)
    assert ctl.v2.display.brand.lower() == front
    ctl.observe_v2(replace(target, event="Stop"))
    ctl.tick()
    assert ctl.v2.display.priority == Priority.P3
    env.advance(3.1)
    assert ctl.v2.display.priority == Priority.P4
    assert ctl.v2.display.brand.lower() != front
    assert ctl.v2.core.ledger.working == 1


def test_unverified_front_does_not_guess_and_two_codex_sessions_rotate(env, tmp_path):
    ctl = enable(env, tmp_path)
    a, b = event(), event(session="s2")
    for e in (a, b):
        ctl.observe_v2(e)
    ctl.tick()
    ctl.v2.core.set_foreground(b.key, verified=False)
    env.advance(1.1)
    assert ctl.v2.display.tasks == (a.key,)
    env.advance(5)
    assert ctl.v2.display.tasks == (b.key,)
    assert ctl.chatgpt.working == 2


def test_claude_legacy_preserves_controls_without_inventing_turn(env, tmp_path):
    ctl = enable(env, tmp_path)
    ctl.handle_event("prompt", meta={"session": "legacy"})
    ctl.tick()
    assert ctl.v2.display.brand == "Claude"
    assert not ctl.v2.display.tasks
    assert ctl.can_interrupt()
    assert ctl.v2.core.ledger.tasks == {}
    ctl.stop_work()
    assert ctl.hub.is_paused and env.win.sprite_name == "stop"
    ctl.resume_work()
    assert not ctl.hub.is_paused
    assert env.state.working_sessions(env.now) == ["legacy"]


def test_permission_queue_preempts_completion_and_claude_only_controls(env, tmp_path):
    ctl = enable(env, tmp_path)
    e = event()
    ctl.observe_v2(e)
    ctl.observe_v2(replace(e, event="Stop"))
    ids = [ctl.hub.permissions.open("Bash", "synthetic", session=s) for s in ("c1", "c2")]
    ctl.tick()
    assert ctl.v2.display.priority == Priority.P1
    assert ctl._perm_panel.request_id == ids[0]
    ctl._on_permission_decided(ids[0], True)
    assert ctl._perm_panel.request_id == ids[1]
    ctl._on_permission_decided(ids[1], False)
    ctl.tick()
    assert not ctl._perm_panel.isVisible()
    assert ctl.v2.display.priority == Priority.P3


@pytest.mark.parametrize("lang", ["zh", "en", "ja"])
def test_chatgpt_permission_is_persistent_read_only_even_muted(env, tmp_path, lang):
    ctl = enable(env, tmp_path)
    ctl.set_language(lang)
    env.data.bubble_muted = True
    e = event()
    ctl.observe_v2(e)
    ctl.observe_v2(replace(e, event="PermissionRequest"))
    ctl.tick()
    hint = ctl._observation_hint
    assert hint.isVisible() and hint.label.wordWrap()
    assert "ChatGPT" in hint.label.text() and "v2_" not in hint.label.text()
    assert hint.findChildren(QPushButton) == []
    assert ctl._perm_panel is None
    rid = ctl.hub.permissions.open("Read", "synthetic", session="claude")
    ctl.tick()
    assert ctl._perm_panel.request_id == rid
    assert ctl._perm_panel._observation_hint.isVisible()
    assert not hint.isVisible()  # One visible copy; never overlapping the Claude controls.
    ctl._on_permission_decided(rid, False)
    ctl.tick()
    assert hint.isVisible()
    ctl.observe_v2(replace(e, event="Stop"))
    ctl.tick()
    assert not hint.isVisible()


def test_reliable_requests_remain_independent_and_resolution_restores_background(env, tmp_path):
    ctl = enable(env, tmp_path)
    core = ctl.v2.core
    core.capabilities[("chatgpt", "codex-local", "global", "unknown")] = SourceCapabilities(True, True)
    a, b = event(), event(provider="claude")
    ctl.observe_v2(b)
    p = replace(a, event="PermissionRequest")
    core.open_request(p, "r1")
    core.open_request(p, "r2")
    core.open_request(p, "r1")
    ctl.tick()
    assert len(core.pending_requests) == 2
    assert ctl.v2.display.priority == Priority.P1
    assert ctl._perm_panel is None
    for rid in ("r1", "r2"):
        core.resolve_request(p, rid)
    ctl.observe_v2(replace(a, event="Stop"))
    ctl.tick()
    env.advance(3.1)
    assert ctl.v2.display.brand == "Claude" and env.win.sprite_name == "working"


def test_duplicate_delayed_events_do_not_repeat_notices_or_revive(env, tmp_path, monkeypatch):
    ctl = enable(env, tmp_path)
    said = []
    monkeypatch.setattr(ctl, "say", lambda text, **kw: said.append(text))
    e = event()
    ctl.observe_v2(e)
    ctl.observe_v2(e)
    ctl.observe_v2(replace(e, event="Stop"))
    ctl.tick()
    assert len(said) == 1
    for _ in range(4):
        ctl.observe_v2(replace(e, event="Stop"))
        ctl.observe_v2(replace(e, event="PreToolUse", tool_use_id="late"))
        ctl.tick()
    assert len(said) == 1 and ctl.chatgpt.working == 0


@pytest.mark.parametrize("variant", ["missing", "source_conflict", "same_ids_other_provider"])
def test_identity_errors_and_provider_separation(env, tmp_path, variant):
    ctl = enable(env, tmp_path)
    e = event()
    ctl.observe_v2(e)
    ctl.observe_v2(replace(e, turn_id="") if variant == "missing" else
                   replace(e, source="project") if variant == "source_conflict" else
                   event(provider="claude"))
    ctl.tick()
    if variant == "same_ids_other_provider":
        assert len(ctl.v2.core.ledger.tasks) == 2
        assert ctl.chatgpt.working == 1
    else:
        assert ctl.v2.display.priority == Priority.P2
        assert env.win.sprite_name == "stop"


def test_independent_leases_heartbeat_recovery_and_long_work(env, tmp_path):
    ctl = enable(env, tmp_path)
    a, b = event(observer="A", leased=True), event(session="b", observer="B", leased=True)
    ctl.observe_v2(a)
    ctl.observe_v2(b)
    for _ in range(180):
        env.mono[0] += 2
        ctl.observe_v2(ObserverHeartbeat("B"))
        ctl.tick()
    ledger = ctl.v2.core.ledger
    assert ledger.tasks[a.key].state == "disconnected"
    assert ledger.tasks[b.key].state == "observed_working"
    ctl.observe_v2(ObserverHeartbeat("A"))
    ctl.tick()
    assert ledger.tasks[a.key].state == "uncertain"
    ctl.observe_v2(a)
    assert ledger.tasks[a.key].state == "uncertain"
    ctl.observe_v2(replace(a, event="PreToolUse", tool_use_id="fresh"))
    ctl.tick()
    assert ledger.working == 2 and env.win.sprite_name == "working"


def test_switch_and_restart_keep_setting_not_live_tasks(env, tmp_path, qapp):
    ctl = enable(env, tmp_path)
    e = event()
    ctl.observe_v2(e)
    ctl.tick()
    ctl.set_v2_scheduler_enabled(False)
    ctl.set_v2_scheduler_enabled(True)
    ctl.observe_v2(e)  # duplicate cannot undo the observation gap
    ctl.tick()
    assert ctl.v2.display.priority == Priority.P2
    env.scheduler.flush()
    saved = load(env.path)
    assert saved.v2_scheduler_enabled
    second = Env(tmp_path / "restart", saved)
    try:
        assert second.ctl.v2.core.enabled
        assert not second.ctl.v2.core.ledger.tasks
        assert second.ctl.v2.display.state == "uncertain"
    finally:
        second.close()
    assert SaveData.from_dict({}).v2_scheduler_enabled is False
    assert SaveData.from_dict({"v2_scheduler_enabled": "true"}).v2_scheduler_enabled is False


def test_disabled_default_keeps_stable_behavior(env):
    ctl = env.ctl
    ctl.observe_v2(event())
    ctl.tick()
    assert not ctl.v2.core.ledger.tasks and env.win.sprite_name == "idle"
    ctl.handle_event("prompt", meta={"session": "legacy"})
    assert env.win.sprite_name == "working"


def test_actual_inbox_poll_uses_one_ledger_and_one_reminder(env, tmp_path, monkeypatch):
    ctl = enable(env, tmp_path)
    # Exercise the real drain path without binding a socket or touching credentials.
    batch = [event(), event("Stop")]
    inbox = SimpleNamespace(drain=lambda: batch[:], degraded=SimpleNamespace(is_set=lambda: False))
    ctl.chatgpt.server = SimpleNamespace(inbox=inbox)
    said = []
    monkeypatch.setattr(ctl, "say", lambda text, **kw: said.append(text))
    ctl.tick()
    ctl.tick()
    assert len(said) == 1
    assert len(ctl.chatgpt.ledger.tasks) == 1
    assert ctl.chatgpt.ledger.received == 4


def test_confirmed_failure_preempts_work_without_changing_background(env, tmp_path):
    ctl = enable(env, tmp_path)
    a, b = event(), event(provider="claude")
    ctl.observe_v2(a)
    ctl.observe_v2(b)
    core = ctl.v2.core
    core.capabilities[("chatgpt", "codex-local", "global", "unknown")] = SourceCapabilities(final_failure=True)
    core.final_failure(a)
    ctl.tick()
    assert ctl.v2.display.priority == Priority.P2 and env.win.sprite_name == "stop"
    assert core.ledger.tasks[b.key].state == "observed_working"
    core.acknowledge(ctl.v2.display)
    ctl.tick()
    assert ctl.v2.display.priority == Priority.P4 and env.win.sprite_name == "working"


def test_idle_requires_explicit_coverage_and_is_not_persisted(env, tmp_path):
    ctl = enable(env, tmp_path)
    ctl.tick()
    assert ctl.v2.display.priority == Priority.P2
    ctl.v2.core.confirm_coverage()  # Synthetic verified snapshot capability only.
    ctl.tick()
    assert ctl.v2.display.priority == Priority.P5
    assert env.win.sprite_name == "idle"
    ctl.set_v2_scheduler_enabled(False)
    ctl.set_v2_scheduler_enabled(True)
    ctl.tick()
    assert ctl.v2.display.priority == Priority.P2


def test_merged_ends_wait_behind_permission_and_only_announce_once(env, tmp_path, monkeypatch):
    ctl = enable(env, tmp_path)
    said = []
    monkeypatch.setattr(ctl, "say", lambda text, **kw: said.append(text))
    rid = ctl.hub.permissions.open("Read", "synthetic", session="claude")
    for s in ("a", "b"):
        ctl.observe_v2(event(session=s))
        ctl.observe_v2(event("Stop", session=s))
    ctl.tick()
    env.advance(4)
    assert len(ctl.v2.core.notices) == 1
    ctl._on_permission_decided(rid, True)
    ctl.tick()
    assert ctl.v2.display.priority == Priority.P3 and len(ctl.v2.display.tasks) == 2
    count = len(said)
    ctl.tick()
    assert len(said) == count
    env.advance(3.1)
    assert not ctl.v2.core.notices


@pytest.mark.parametrize("height", [120, 200, 600])
def test_permission_hint_at_different_pet_sizes_does_not_add_controls(env, tmp_path, height):
    ctl = enable(env, tmp_path)
    ctl.set_size(height)
    ctl.observe_v2(event("PermissionRequest"))
    ctl.tick()
    hint = ctl._observation_hint
    assert hint.width() == 300
    assert hint.height() >= hint.label.heightForWidth(hint.label.width())
    assert not hint.findChildren(QPushButton)


def test_chatgpt_disable_does_not_disconnect_identified_claude(env, tmp_path):
    ctl = enable(env, tmp_path)
    a = event(provider="claude")
    ctl.observe_v2(a)
    ctl.observe_v2(event())
    ctl.toggle_chatgpt()
    assert ctl.v2.core.ledger.tasks[a.key].state == "observed_working"
    assert not ctl.chatgpt.enabled
