"""a55825f review regressions; synthetic metadata and isolated Qt only."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt

from shion.chatgpt import ChatGPTConnection
from shion.events import ObserverHeartbeat
from shion.scheduler import Priority, SourceCapabilities
from tests.test_controller import env, qapp  # noqa: F401
from tests.test_scheduler_gui import enable, event


class Inbox:
    def __init__(self, *events):
        self.batch = list(events)
        self.degraded = Event()
        self.enabled = True

    def drain(self):
        events, self.batch = self.batch, []
        return events


@pytest.mark.parametrize("cause", ["toggle", "inbox"])
@pytest.mark.parametrize("identified", [False, True])
def test_chatgpt_gap_cannot_permanently_preempt_claude(env, tmp_path, cause, identified):
    ctl = enable(env, tmp_path)
    old = event()
    ctl.observe_v2(old)
    inbox = Inbox()
    ctl.chatgpt.server = SimpleNamespace(inbox=inbox)
    if cause == "toggle":
        ctl.toggle_chatgpt()
        ctl.toggle_chatgpt()
    else:
        inbox.degraded.set()
        ctl.tick()
    # A duplicate is not evidence of continuous work across the gap.
    ctl.observe_v2(old)
    assert ctl.chatgpt.working == 0
    if identified:
        ctl.observe_v2(event(provider="claude"))
    else:
        ctl.handle_event("prompt", meta={"session": "legacy"})
    ctl.tick()
    assert ctl.v2.display.priority == Priority.P4
    assert ctl.v2.display.brand == "Claude" and env.win.sprite_name == "working"
    assert not ctl.chatgpt.ledger.uncertain
    assert not inbox.degraded.is_set()
    # A new identified turn can finish without reviving the old unknown turn.
    new = event(turn="new")
    inbox.batch = [new, replace(new, event="Stop")]
    ctl.tick()
    env.advance(3.1)
    assert ctl.v2.display.priority == Priority.P4
    assert ctl.chatgpt.working == 0
    assert not ctl.chatgpt.ledger.tasks[old.key].terminal


def test_real_lease_loss_stays_visible_and_pulse_never_revives_old_work(env, tmp_path):
    ctl = enable(env, tmp_path)
    old = event(leased=True, observer="lost")
    ctl.observe_v2(old)
    ctl.handle_event("prompt", meta={"session": "legacy"})
    env.mono[0] += 10
    ctl.tick()
    assert ctl.v2.display.priority == Priority.P2
    assert ctl.v2.display.state == "disconnected" and env.win.sprite_name == "stop"
    assert ctl.lines.ui("v2_disconnected") in ctl.v2.text(ctl.lines.ui)
    ctl.observe_v2(ObserverHeartbeat("lost"))
    ctl.observe_v2(old)
    ctl.tick()
    assert ctl.chatgpt.working == 0
    assert ctl.chatgpt.ledger.tasks[old.key].state == "uncertain"
    assert ctl.v2.display.priority == Priority.P4  # Recovered transport, separate Claude work.
    ctl.observe_v2(replace(old, event="PreToolUse", tool_use_id="fresh"))
    assert ctl.chatgpt.working == 1


@pytest.mark.parametrize("lang", ["zh", "en", "ja"])
@pytest.mark.parametrize("state", ["connected", "disconnected", "stale", "error"])
def test_claude_connection_row_survives_v2_status(env, tmp_path, monkeypatch, lang, state):
    ctl = enable(env, tmp_path)
    ctl.set_language(lang)
    ctl.connection.inspect = lambda: SimpleNamespace(state=state, detail="connection detail")
    full = ctl.v2.text(ctl.lines.ui) + " " + "long status " * 40
    monkeypatch.setattr(ctl.v2, "text", lambda ui: full)
    menu = ctl.build_menu()
    row = menu.actions()[6]
    ui = ctl.lines.ui
    full_row = ui("menu_link_status", name=ui("menu_claude"), state=ui("connection_" + state),
                  activity=ui("activity_link_idle"))
    assert row.text() == menu.fontMetrics().elidedText(full_row, Qt.ElideRight, 240)
    assert not row.isEnabled()
    status = menu.actions()[7]
    assert status.text() == menu.fontMetrics().elidedText(full, Qt.ElideRight, 240)
    assert not status.isEnabled() and status.toolTip() == full


@pytest.mark.parametrize("leased", [False, True])
def test_switch_marks_unknown_without_chatgpt_disconnect_notice(env, tmp_path, monkeypatch, leased):
    ctl = enable(env, tmp_path)
    monkeypatch.setattr(ctl._idle, "step", lambda *args: None)  # Normal idle actions may choose happy.
    old = event(leased=leased, observer="observer" if leased else "")
    ctl.observe_v2(old)
    ctl.observe_v2(event(provider="claude"))
    ctl.observe_v2(event("Stop", session="ended"))
    ctl.v2.core.confirm_coverage()
    said = []
    monkeypatch.setattr(ctl, "say", lambda text, **kw: said.append(text))
    ctl.set_v2_scheduler_enabled(False)
    ctl.tick()
    assert not said
    assert all(t.state == "uncertain" and t.continuity_lost
               for t in ctl.v2.core.ledger.tasks.values() if not t.terminal)
    assert not ctl.v2.core.coverage_known and not ctl.v2.core.notices
    env.mono[0] += 20  # A deliberately paused observation is not a transport failure.
    ctl.set_v2_scheduler_enabled(True)
    ctl.tick()
    assert ctl.chatgpt.working == 0
    assert ctl.v2.display.state == "uncertain"
    assert env.win.sprite_name == "idle"
    assert not any(ctl.lines.ui(k) in s for s in said for k in ("chatgpt_disconnected", "chatgpt_disconnected_say"))


@pytest.mark.parametrize("entry", ["tick", "switch", "observe"])
def test_attach_conflict_logs_and_falls_back_without_aborting(env, tmp_path, caplog, entry):
    ctl = env.ctl
    ctl.set_v2_scheduler_enabled(True)
    ctl.observe_v2(event(provider="claude"))
    ctl.chatgpt = ChatGPTConnection(tmp_path / "data", tmp_path / "codex")
    ctl.chatgpt.server = SimpleNamespace(inbox=Inbox(event()))
    with caplog.at_level("WARNING"):
        if entry == "switch":
            ctl.set_v2_scheduler_enabled(True)
        elif entry == "observe":
            ctl.observe_v2(event())
        ctl.tick()
    assert not ctl.v2.core.enabled
    assert ctl.chatgpt.working == 1 and env.win.sprite_name == "working"
    assert "attach" in caplog.text.lower()


def test_inbox_heartbeat_runs_core_request_maintenance(env, tmp_path):
    ctl = enable(env, tmp_path)
    e = event(leased=True, observer="pulse")
    core = ctl.v2.core
    core.capabilities[(e.provider, e.namespace, e.source, e.client_surface)] = SourceCapabilities(True)
    core.observe(e)
    core.open_request(replace(e, event="PermissionRequest"), "request")
    env.mono[0] += 11
    ctl.chatgpt.server = SimpleNamespace(inbox=Inbox(ObserverHeartbeat("pulse")))
    ctl.chatgpt.poll()  # No subsequent GUI select to hide a missed maintenance call.
    assert core.requests[e.key, "request"].status == "unknown"
    assert ctl.chatgpt.working == 0


def test_queue_gap_discards_ambiguous_batch_and_still_detects_lease_loss(env, tmp_path):
    ctl = enable(env, tmp_path)
    old = event(leased=True, observer="observer")
    ctl.observe_v2(old)
    inbox = Inbox(event(turn="ambiguous"))
    inbox.degraded.set()
    ctl.chatgpt.server = SimpleNamespace(inbox=inbox)
    ctl.tick()
    assert event(turn="ambiguous").key not in ctl.chatgpt.ledger.tasks
    assert ctl.chatgpt.working == 0
    assert ctl.v2.display.state == "uncertain"
    assert ctl.lines.ui("v2_uncertain") in ctl.v2.text(ctl.lines.ui)
    env.mono[0] += 10
    ctl.tick()
    assert ctl.v2.display.state == "disconnected" and env.win.sprite_name == "stop"
    inbox.batch = [ObserverHeartbeat("observer")]
    ctl.tick()
    assert ctl.chatgpt.working == 0 and ctl.v2.display.state == "uncertain"
    inbox.batch = [replace(old, event="PostToolUse", tool_use_id="fresh")]
    ctl.tick()
    assert ctl.chatgpt.working == 1 and ctl.v2.display.priority == Priority.P4


def test_new_reliable_request_after_switch_is_leased_but_old_request_stays_unknown(env, tmp_path):
    ctl = enable(env, tmp_path)
    e = event(leased=True, observer="observer")
    core = ctl.v2.core
    core.capabilities[(e.provider, e.namespace, e.source, e.client_surface)] = SourceCapabilities(True)
    core.observe(e)
    request = replace(e, event="PermissionRequest")
    core.open_request(request, "old")
    ctl.set_v2_scheduler_enabled(False)
    ctl.set_v2_scheduler_enabled(True)
    core.open_request(request, "old")
    assert not core.pending_requests
    core.open_request(replace(request, tool_use_id="fresh"), "new")
    assert core.pending_requests == ((e.key, "new"),)
    env.mono[0] += 10
    assert not core.pending_requests
    assert core.select().state == "disconnected"


def test_packet_received_before_switch_cannot_restore_work_or_human_wait(env, tmp_path):
    ctl = enable(env, tmp_path)
    e = event()
    ctl.observe_v2(e)
    old_received = env.mono[0]
    env.mono[0] += 1
    ctl.set_v2_scheduler_enabled(False)
    ctl.set_v2_scheduler_enabled(True)
    ctl.observe_v2(replace(e, event="PreToolUse", tool_use_id="delayed", received_at=old_received))
    assert ctl.chatgpt.working == 0
    core = ctl.v2.core
    core.capabilities[(e.provider, e.namespace, e.source, e.client_surface)] = SourceCapabilities(True)
    core.open_request(replace(e, event="PermissionRequest", received_at=old_received), "delayed")
    assert not core.pending_requests
    env.mono[0] += 1
    ctl.observe_v2(replace(e, event="PreToolUse", tool_use_id="new", received_at=env.mono[0]))
    assert ctl.chatgpt.working == 1


def menu_snapshot(menu):
    return [{"text": a.text(), "separator": a.isSeparator(), "enabled": a.isEnabled(),
             "checked": a.isChecked(), "checkable": a.isCheckable(), "tooltip": a.toolTip(),
             "children": menu_snapshot(a.menu()) if a.menu() is not None else []}
            for a in menu.actions()]


@pytest.mark.parametrize("lang", ["zh", "en", "ja"])
def test_disabled_matches_a55825f_menu_status_and_counts(env, tmp_path, lang):
    ctl = env.ctl
    ctl.set_language(lang)
    ctl.connection.inspect = lambda: SimpleNamespace(state="connected", detail="baseline detail")
    ctl.chatgpt = ChatGPTConnection(tmp_path / "data", tmp_path / "codex")
    inbox = Inbox()
    ctl.chatgpt.server = SimpleNamespace(inbox=inbox)
    trace = []
    for stage in ("idle", "working", "permission", "ended", "degraded", "disabled", "reenabled"):
        if stage == "working":
            inbox.batch = [event(), event(provider="claude")]
        elif stage == "permission":
            inbox.batch = [event("PermissionRequest")]
        elif stage == "ended":
            inbox.batch = [event("Stop")]
        elif stage == "degraded":
            inbox.degraded.set()
        elif stage in ("disabled", "reenabled"):
            ctl.toggle_chatgpt()
        ctl.tick()
        assert not ctl.v2.core.enabled and not ctl.v2.core.ledger.tasks
        menu = json.dumps(menu_snapshot(ctl.build_menu()), ensure_ascii=False, sort_keys=True)
        trace.append({"stage": stage, "menu_sha256": sha256(menu.encode("utf-8")).hexdigest(),
                      "status": ctl.status_text(), "chatgpt_status": ctl.chatgpt.status(ctl.lines.ui),
                      "working": ctl.chatgpt.working,
                      "received": ctl.chatgpt.ledger.received_by_provider.get("chatgpt", 0),
                      "sprite": env.win.sprite_name})
    baseline = Path(__file__).with_name("fixtures") / "scheduler_disabled_a55825f.json"
    assert trace == json.loads(baseline.read_text(encoding="utf-8"))[lang]
