"""Lease semantics with deterministic time and isolated stdio/HTTP transports."""
from dataclasses import replace
import json
import subprocess
import time

import pytest

from shion.codex_mcp import HeartbeatSender, dispatch
from shion.events import ObserverHeartbeat, parse_observation, parse_heartbeat
from shion.observer import ObservationServer
from shion.tasks import TaskLedger


def event(kind="PreToolUse", session="s", turn="t", observer="a", tool="tool", **extra):
    return parse_observation(dict(event=kind, session_id=session, turn_id=turn,
        observer=observer, leased=True, tool_use_id=tool, **extra))


def test_quiet_long_task_uses_heartbeats_not_hook_silence():
    now = [0.0]
    ledger = TaskLedger(clock=lambda: now[0])
    ledger.accept(event())
    ledger.accept(event("PermissionRequest", tool=""))
    for second in range(2, 3602, 2):
        now[0] = float(second)
        ledger.heartbeat(ObserverHeartbeat("a"))
        assert ledger.working == 1
    assert ledger.received == 2  # Heartbeats are not lifecycle events.
    assert ledger.pending  # Permission outcome remains independently unknown.
    ledger.accept(event("Stop"))
    assert ledger.working == 0 and not ledger.pending
    assert ledger.tasks[event().key].result == "unknown"


def test_disconnect_duplicate_recovery_and_terminal_tombstone():
    now = [0.0]
    ledger = TaskLedger(clock=lambda: now[0])
    start = event()
    ledger.accept(start)
    now[0] = 9.999
    assert ledger.working == 1
    now[0] = 10.0
    assert ledger.working == 0 and ledger.disconnected and ledger.pending
    task = ledger.tasks[start.key]
    assert not task.terminal and task.result == "unknown"
    now[0] = 11.0
    ledger.heartbeat(ObserverHeartbeat("a"))
    assert task.state == "disconnected"  # Next evaluation reports restored but unknown.
    assert ledger.working == 0 and task.state == "uncertain"
    ledger.accept(start)
    assert ledger.working == 0  # Replayed Pre is not fresh task evidence.
    ledger.accept(event("PostToolUse"))
    assert ledger.working == 1
    assert ledger.accept(event("Stop")) == "turn_ended"
    now[0] = 25
    ledger.heartbeat(ObserverHeartbeat("a"))
    ledger.accept(event(tool="late"))
    assert ledger.working == 0 and task.terminal and task.result == "unknown"


def test_gap_without_polling_does_not_revive_on_first_pulse():
    now = [0.0]
    ledger = TaskLedger(clock=lambda: now[0])
    ledger.accept(event())
    now[0] = 50
    ledger.heartbeat(ObserverHeartbeat("a"))
    assert ledger.working == 0 and ledger.pending


def test_queue_disconnect_with_live_observer_recovers_only_to_unknown():
    now = [0.0]
    ledger = TaskLedger(clock=lambda: now[0])
    ledger.accept(event())
    ledger.disconnect()
    now[0] = 2
    ledger.heartbeat(ObserverHeartbeat("a"))
    assert ledger.working == 0 and ledger.pending and not ledger.disconnected
    assert ledger.tasks[event().key].state == "uncertain"


def test_concurrent_observers_cannot_renew_each_others_tasks():
    now = [0.0]
    ledger = TaskLedger(clock=lambda: now[0])
    ledger.accept(event(session="a", observer="a"))
    ledger.accept(event(session="b", observer="b"))
    for second in range(2, 22, 2):
        now[0] = second
        ledger.heartbeat(ObserverHeartbeat("b"))
    assert ledger.working == 1
    assert ledger.tasks[event(session="a").key].state == "disconnected"
    ledger.accept(event("Stop", session="a", observer="a"))
    assert ledger.working == 1


def test_legacy_observer_keeps_300_second_unknown_fallback():
    now = [0.0]
    ledger = TaskLedger(clock=lambda: now[0])
    ledger.accept(replace(event(), leased=False))
    now[0] = 299.99
    assert ledger.working == 1
    now[0] = 300
    assert ledger.working == 0 and ledger.pending and not ledger.disconnected


def test_single_missed_pulse_does_not_mark_long_task_lost():
    now = [0.0]
    ledger = TaskLedger(clock=lambda: now[0])
    ledger.accept(event())
    now[0] = 8
    ledger.heartbeat(ObserverHeartbeat("a"))
    now[0] = 16
    assert ledger.working == 1 and not ledger.pending


def test_deliberate_disable_has_no_loss_notice(tmp_path):
    from shion.chatgpt import ChatGPTConnection
    connection = ChatGPTConnection(tmp_path / "private", tmp_path / "codex")
    connection.ledger.accept(event())
    connection.toggle()
    assert not connection.enabled and connection.poll() is None


def test_buffered_packets_use_receiver_time_and_tables_are_bounded():
    ledger = TaskLedger(clock=lambda: 20.0, capacity=2)
    ledger.accept(replace(event(), received_at=0.0))
    ledger.heartbeat(ObserverHeartbeat("a", received_at=1.0))
    assert ledger.working == 0
    ledger.heartbeat(ObserverHeartbeat("b", received_at=20.0))
    ledger.heartbeat(ObserverHeartbeat("c", received_at=20.0))
    assert len(ledger.leases) == 2 and ledger.pending


@pytest.mark.parametrize("payload", [{"observer": "a", "prompt": "private"},
    {"observer": "a", "received_at": 0}, {"observer": ""}, {"observer": []}])
def test_heartbeat_metadata_allowlist(payload):
    with pytest.raises(ValueError):
        parse_heartbeat(payload)


def test_hook_cannot_assign_transport_capability(tmp_path):
    for field, value in (("observer", "a"), ("leased", True)):
        with pytest.raises(ValueError):
            dispatch({"method": "tools/call", "params": {"name": "observe_lifecycle",
                "arguments": {"event": "Stop", field: value}}}, tmp_path, "o")


def private_config(tmp_path, port):
    from shion import observer_files as secure
    directory = secure.ensure_directory(tmp_path / "private")
    secure.write_new(directory / "chatgpt-observer.json", json.dumps(
        {"token": "a" * 64, "port": port, "enabled": True}).encode())
    return directory


def test_heartbeat_sender_is_independent_and_stops_cleanly(tmp_path):
    server = ObservationServer("a" * 64, port=0)
    directory = private_config(tmp_path, server.server.server_port)
    server.start()
    try:
        with HeartbeatSender(directory, "pulse", interval=0.02) as sender:
            received, deadline = [], time.monotonic() + 3
            while len(received) < 2 and time.monotonic() < deadline:
                received += server.inbox.drain()
                time.sleep(0.01)
        assert not sender.thread.is_alive()
        assert len(received) >= 2
        assert all(isinstance(e, ObserverHeartbeat) and e.received_at is not None for e in received)
    finally:
        server.stop()


def test_killed_isolated_stdio_observer_expires_without_completion(tmp_path):
    from shion.chatgpt import observer_command
    server = ObservationServer("a" * 64, port=0)
    directory = private_config(tmp_path, server.server.server_port)
    server.start()
    process = subprocess.Popen(observer_command() + ["--data-dir", str(directory)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=tmp_path)
    try:
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "observe_lifecycle", "arguments": {"event": "PreToolUse", "source": "global",
            "session_id": "isolated", "turn_id": "turn", "tool_use_id": "tool"}}}
        process.stdin.write(json.dumps(request) + "\n")
        process.stdin.flush()
        # Bounded receiver wait rather than an unbounded stdout readline.
        packets, deadline = [], time.monotonic() + 5
        while not any(getattr(p, "event", "") == "PreToolUse" for p in packets) and time.monotonic() < deadline:
            packets += server.inbox.drain()
            time.sleep(0.01)
        assert any(getattr(p, "event", "") == "PreToolUse" for p in packets)
        process.kill()  # Only this Popen-owned test process, never a real Observer.
        stdout, stderr = process.communicate(timeout=5)
        assert not stderr
        assert json.loads(stdout)["result"]["isError"] is False
        now = [time.monotonic()]
        ledger = TaskLedger(clock=lambda: now[0])
        for packet in packets + server.inbox.drain():
            if isinstance(packet, ObserverHeartbeat):
                ledger.heartbeat(packet)
            else:
                ledger.accept(packet)
        assert ledger.working == 1
        now[0] += 10.01
        assert ledger.working == 0 and ledger.disconnected
        assert all(not t.terminal and t.result == "unknown" for t in ledger.tasks.values())
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
        server.stop()
