"""Simulated acceptance of the opt-in core, not client/GUI acceptance."""
from dataclasses import replace
from pathlib import Path

import pytest

from shion.events import Observation, ObserverHeartbeat
from shion.scheduler import Priority, Scheduler, SourceCapabilities


def event(kind="UserPromptSubmit", provider="claude", namespace="claude-local", session="s", turn="t", **kw):
    return Observation(kind, session_id=session, turn_id=turn, provider=provider, namespace=namespace, **kw)


@pytest.fixture
def core():
    now = [0.0]
    scheduler = Scheduler(enabled=True, clock=lambda: now[0], capabilities={
        ("claude", "claude-local", "global", "unknown"): SourceCapabilities(True, True, True)})
    return scheduler, now


def test_default_off_and_no_production_gui_import():
    scheduler = Scheduler()
    scheduler.observe(event())
    scheduler.open_request(event("PermissionRequest"), "r")
    scheduler.confirm_coverage()
    assert scheduler.select() is None and not scheduler.ledger.tasks and not scheduler.requests
    root = Path(__file__).resolve().parents[1]
    for file in ("controller.py", "app.py", "bridge.py", "state.py"):
        assert "import Scheduler" not in (root / "shion" / file).read_text(encoding="utf-8")


def test_identity_isolation_background_and_ui_brands(core):
    s, _ = core
    events = [event(), event(provider="chatgpt", namespace="codex-local"),
              event(namespace="other-runtime"), event(session="other"), event(turn="next")]
    for e in events:
        s.observe(e)
    assert s.ledger.working == 5
    assert {d.brand for d in s.candidates()} == {"Claude", "ChatGPT"}
    s.observe(replace(events[0], event="Stop"))
    assert s.ledger.working == 4
    s.observe(replace(events[0], event="PreToolUse", tool_use_id="late"))
    assert s.ledger.working == 4
    assert len(s.notices) == 1


def test_p1_to_p5_and_neutral_completion(core):
    s, now = core
    s.confirm_coverage()
    assert (s.select().priority, s.select().state) == (Priority.P5, "idle")
    a, b = event(), event(session="background")
    s.observe(a)
    assert s.select().priority == Priority.P4
    s.observe(replace(b, event="Stop"))
    assert s.select().priority == Priority.P3
    assert s.select().result == "unknown"
    s.final_failure(event(session="failed"))
    assert s.select().priority == Priority.P2
    s.open_request(replace(a, event="PermissionRequest"), "human")
    assert s.select().priority == Priority.P1  # Preempts higher display hold immediately.
    s.resolve_request(a, "human")
    assert s.select().priority == Priority.P2
    assert s.ledger.tasks[a.key].state == "uncertain"  # Answer is not resumed work.
    now[0] = 31
    s.observe(replace(a, event="Stop"))
    s.acknowledge(s.select())
    assert s.select().priority == Priority.P5


def test_foreground_with_hysteresis_does_not_cross_priority(core):
    s, now = core
    a, b = event(), event(session="b")
    s.observe(a)
    s.observe(b)
    assert s.select().tasks == (a.key,)
    s.set_foreground(b.key, verified=True)
    now[0] = .5
    assert s.select().tasks == (a.key,)  # Minimum hold.
    now[0] = 1.1
    assert s.select().tasks == (b.key,)
    s.set_foreground(a.key)  # A guessed process/window identity must be ignored.
    now[0] = 2.2
    assert s.select().tasks == (b.key,)
    s.open_request(replace(a, event="PermissionRequest"), "r")
    assert s.select().tasks == (a.key,) and s.select().priority == Priority.P1
    assert s.ledger.tasks[b.key].state == "observed_working"


def test_unknown_foreground_fair_rotation_and_higher_priority(core):
    s, now = core
    a, b = event(), event(session="b")
    s.observe(a)
    s.observe(b)
    assert s.select().tasks == (a.key,)
    now[0] = 5.1
    assert s.select().tasks == (b.key,)
    now[0] = 10.2
    assert s.select().tasks == (a.key,)
    s.observe(event("Stop", session="c"))
    assert s.select().priority == Priority.P3


def test_independent_p1_requests_duplicate_and_resolution_tombstones(core):
    s, now = core
    a = event("PermissionRequest")
    s.open_request(a, "one")
    s.open_request(a, "one")
    assert not s.ledger.tasks[a.key].permission_unknown
    s.open_request(a, "two")
    s.open_request(replace(a, session_id="b"), "one")
    assert len(s.pending_requests) == 3
    first = s.select()
    s.acknowledge(first)
    assert len(s.pending_requests) == 3  # Acknowledging UI does not resolve a real request.
    now[0] = 5.1
    assert s.select().request_id == "two"
    s.resolve_request(a, "one")
    s.open_request(a, "one")
    assert len(s.pending_requests) == 2
    s.resolve_request(a, "future")
    s.open_request(a, "future")
    assert len(s.pending_requests) == 2
    s.observe(replace(a, event="Stop"))
    assert len(s.pending_requests) == 1  # Only the other session remains open.


def test_chatgpt_permissions_and_tool_errors_do_not_invent_capabilities(core):
    s, _ = core
    a = event(provider="chatgpt", namespace="codex-local")
    s.observe(a)
    s.open_request(replace(a, event="PermissionRequest"), "synthetic-request")
    s.resolve_request(a, "synthetic-request")
    s.final_failure(a)
    s.observe(replace(a, event="PostToolUse", tool_use_id="tool"))
    assert not s.pending_requests
    task = s.ledger.tasks[a.key]
    assert task.permission_unknown and not task.terminal and task.result == "unknown"
    assert s.select().state == "uncertain"


def test_client_capabilities_and_full_ids_remain_separate():
    s = Scheduler(enabled=True, capabilities={
        ("chatgpt", "codex-local", "global", "cli"): SourceCapabilities(human_wait=True)})
    cli = event("PermissionRequest", provider="chatgpt", namespace="codex-local",
                session="sameprefix-cli", client_surface="cli")
    desktop = replace(cli, session_id="sameprefix-desktop", client_surface="desktop")
    s.open_request(cli, "r")
    s.open_request(desktop, "r")
    assert s.pending_requests == ((cli.key, "r"),)
    assert len(s.ledger.tasks) == 2
    assert s.ledger.tasks[desktop.key].permission_unknown
    assert any(c[2] == "desktop" for c in s.ledger.tasks[desktop.key].contexts)


def test_reminders_merge_dedup_queue_and_no_terminal_revival(core):
    s, now = core
    for i in range(5):
        e = event("Stop", session=str(i))
        s.observe(e)
        s.observe(e)
    assert len(s.notices) == 1 and len(s.select().tasks) == 5
    s.acknowledge(s.select())
    s.observe(event("Stop", session="0"))
    assert not s.notices
    now[0] = 3
    s.observe(event("Interrupt", session="new"))
    assert s.select().state == "interrupted" and s.select().result == "unknown"
    assert all(task.result == "unknown" for task in s.ledger.tasks.values())


def test_queue_pressure_is_visible_and_keeps_p1():
    s = Scheduler(enabled=True, notice_capacity=1, capabilities={
        ("claude", "claude-local", "global", "unknown"): SourceCapabilities(True)})
    s.observe(event("Stop"))
    s.observe(event("Interrupt", session="b"))
    assert s.degraded and s.select().state == "uncertain"
    s.open_request(event("PermissionRequest", session="c"), "r")
    assert s.select().priority == Priority.P1 and len(s.pending_requests) == 1


def test_disconnect_scope_merge_recovery_and_stale_requests(core):
    s, now = core
    a, b = event(leased=True, observer="one"), event(session="b", leased=True, observer="one")
    c = event(provider="chatgpt", namespace="codex-local", leased=True, observer="two")
    for e in (a, b, c):
        s.observe(e)
    s.open_request(replace(a, event="PermissionRequest"), "r")
    now[0] = 9
    s.heartbeat(ObserverHeartbeat("two"))
    now[0] = 10
    assert s.select().state == "disconnected"
    assert set(s.select().tasks) == {a.key, b.key}
    assert s.ledger.working == 1 and not s.pending_requests
    now[0] = 11
    s.heartbeat(ObserverHeartbeat("one"))
    assert s.select().state == "uncertain"
    s.observe(replace(a, event="PreToolUse", tool_use_id="fresh"))
    assert s.ledger.working == 2
    assert not s.pending_requests  # Transport recovery never restores old human-wait claims.
    assert s.ledger.tasks[a.key].permission_unknown


def test_unknown_start_missing_ids_and_state_expiry(core):
    s, now = core
    assert s.select().state == "uncertain"
    s.observe(event("SessionStart", turn=""))
    assert not s.ledger.tasks and s.select().state == "uncertain"
    s.observe(event())
    now[0] = 300
    assert s.select().state == "uncertain"
    assert s.ledger.working == 0 and not s.ledger.tasks[event().key].terminal
    s.observe(event(session="", turn=""))
    s.confirm_coverage()
    assert s.select().state == "uncertain"


def test_10_sessions_6000_simulated_events_remain_independent(core):
    s, now = core
    for i in range(6000):
        now[0] = i / 100
        e = event("PreToolUse" if i % 2 else "PostToolUse", session=str(i % 10),
                  tool_use_id=str(i), provider="claude" if i % 2 else "chatgpt", namespace="runtime")
        s.observe(e)
        s.observe(e)
        assert s.select().priority == Priority.P4
    assert s.ledger.working == 10 and len(s.ledger.tasks) == 10
    assert s.ledger.duplicates == 6000
    for key in list(s.ledger.tasks):
        s.observe(event("Stop", provider=key[0], namespace=key[1], session=key[2], turn=key[3]))
    assert s.ledger.working == 0
    assert sum(len(n.display.tasks) for n in s.notices.values()) == 10
