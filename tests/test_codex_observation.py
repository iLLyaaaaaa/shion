import http.client
import json
import subprocess
import sys
import time

import pytest

from shion.events import parse_observation
from shion.tasks import TaskLedger
from shion.observer import ObservationInbox, ObservationServer
from shion.codex_mcp import dispatch


def event(kind, session="s", turn="t", **extra):
    return parse_observation(dict(event=kind, session_id=session, turn_id=turn, **extra))


def test_independent_turns_and_terminal_tombstones():
    ledger = TaskLedger()
    for s, t in (("a", "1"), ("a", "2"), ("b", "1")):
        ledger.accept(event("PreToolUse", s, t, tool_use_id="tool"))
    assert ledger.working == 3
    assert ledger.accept(event("Stop", "a", "1")) == "turn_ended"
    assert ledger.accept(event("Stop", "a", "1")) is None
    ledger.accept(event("PreToolUse", "a", "1", tool_use_id="late"))
    assert ledger.working == 2
    assert all(t.result == "unknown" for t in ledger.tasks.values())
    ledger.accept(event("Interrupt", "b", "1"))
    assert ledger.working == 1


def test_missing_identity_permission_stale_and_capacity():
    now = [0]
    ledger = TaskLedger(clock=lambda: now[0], capacity=2, ttl=10)
    ledger.accept(event("SessionStart"))
    assert not ledger.tasks
    ledger.accept(event("PreToolUse", turn=""))
    assert ledger.pending and not ledger.tasks
    ledger.accept(event("PermissionRequest"))
    assert ledger.pending and ledger.working == 0
    ledger.accept(event("PostToolUse"))
    assert ledger.working == 1 and ledger.pending
    now[0] = 11
    assert ledger.working == 0
    ledger.accept(event("PreToolUse", session="b"))
    ledger.accept(event("PreToolUse", session="c"))
    assert len(ledger.tasks) == 2


def test_duplicate_sources_do_not_double_count():
    ledger = TaskLedger()
    ledger.accept(event("PreToolUse", source="global", tool_use_id="x"))
    ledger.accept(event("PreToolUse", source="project", tool_use_id="x"))
    assert ledger.working == 1 and ledger.pending and ledger.duplicates == 1


def test_permission_preserves_activity_until_terminal_or_expiry():
    now = [0.0]
    ledger = TaskLedger(clock=lambda: now[0])
    ledger.accept(event("PreToolUse", tool_use_id="tool"))
    ledger.accept(event("PermissionRequest"))
    now[0] = 299.9
    assert ledger.working == 1 and ledger.pending
    ledger.accept(event("PostToolUse", tool_use_id="tool"))
    assert ledger.working == 1 and ledger.pending
    ledger.accept(event("Stop"))
    assert ledger.working == 0
    ledger.accept(event("PermissionRequest"))
    assert ledger.working == 0


def test_permission_does_not_revive_disconnected_or_expired_work():
    now = [0.0]
    ledger = TaskLedger(clock=lambda: now[0])
    ledger.accept(event("PermissionRequest"))
    assert ledger.working == 0
    ledger.accept(event("PreToolUse", tool_use_id="tool"))
    ledger.accept(event("PermissionRequest"))
    now[0] = 300
    ledger.accept(event("PermissionRequest"))
    assert ledger.working == 0
    ledger.accept(event("PreToolUse", tool_use_id="other"))
    ledger.disconnect()
    ledger.accept(event("PermissionRequest"))
    assert ledger.working == 0


def test_observation_log_is_short_metadata_and_fail_open(caplog, monkeypatch):
    from shion.chatgpt import log_observation, log
    observation = event("PermissionRequest", session="abcdefgh-private", turn="ijklmnop-private")
    with caplog.at_level("INFO", logger="shion.chatgpt"):
        log_observation(observation)
    assert "PermissionRequest" in caplog.text
    assert "abcdefgh" in caplog.text and "ijklmnop" in caplog.text
    assert "private" not in caplog.text
    def fail(*args, **kwargs):
        raise OSError("unavailable")
    monkeypatch.setattr(log, "info", fail)
    log_observation(observation)


@pytest.mark.parametrize("extra", [{"prompt": "secret"}, {"tool_input": {}}, {"token": "secret"},
                                    {"session_id": "x" * 129}, {"turn_id": "${turn_id}"}])
def test_metadata_rejects_content_and_bad_ids(extra):
    with pytest.raises(ValueError):
        parse_observation({"event": "Stop", **extra})


def test_bounded_queue_and_auth():
    inbox = ObservationInbox("secret", capacity=1)
    assert inbox.submit("wrong", {"event": "Stop"}) == 403
    assert inbox.submit("secret", {"event": "Stop"}) == 204
    assert inbox.submit("secret", {"event": "Stop"}) == 503
    assert inbox.degraded.is_set()
    assert len(inbox.drain()) == 1
    inbox.enabled = False
    assert inbox.submit("secret", {"event": "Stop"}) == 204
    assert not inbox.drain()


def test_http_isolation_and_mcp_transport(tmp_path):
    server = ObservationServer("a" * 64, port=0)
    server.start()
    config = {"token": "a" * 64, "port": server.server.server_port, "enabled": True}
    from shion import observer_files as secure
    tmp_path = secure.ensure_directory(tmp_path / "private")
    secure.write_new(tmp_path / "chatgpt-observer.json", json.dumps(config).encode())
    try:
        result = dispatch({"method": "tools/call", "params": {"name": "observe_lifecycle",
            "arguments": {"event": "Stop", "source": "global", "session_id": "s", "turn_id": "t"}}}, tmp_path, "o")
        assert result["content"][0]["text"] == "{}"
        assert server.inbox.drain()[0].session_id == "s"
        conn = http.client.HTTPConnection("127.0.0.1", server.server.server_port, timeout=1)
        conn.request("POST", "/permission/open", "{}")
        assert conn.getresponse().status == 403
        conn.close()
    finally:
        server.stop()
    start = time.monotonic()
    result = dispatch({"method": "tools/call", "params": {"name": "observe_lifecycle",
        "arguments": {"event": "Stop", "source": "global"}}}, tmp_path, "o")
    assert time.monotonic() - start < 1
    assert result["isError"] is False


def test_stdio_mcp_roundtrip_from_unrelated_directory(tmp_path):
    from shion.chatgpt import observer_command
    requests = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "observe_lifecycle", "arguments": {"event": "Stop"}}}]
    result = subprocess.run(observer_command() + ["--data-dir", str(tmp_path)], cwd=tmp_path,
                            input="\n".join(map(json.dumps, requests)) + "\n", text=True,
                            capture_output=True, timeout=10)
    assert result.returncode == 0 and not result.stderr
    replies = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(replies) == 3
    assert replies[0]["result"]["protocolVersion"] == "2025-06-18"
    assert replies[2]["result"]["content"] == [{"type": "text", "text": "{}"}]


def test_observer_entry_does_not_import_gui(tmp_path):
    code = "from shion.__main__ import main; import sys; main(['--codex-observer','--data-dir',sys.argv[1]]); assert not any(x.startswith('PySide6') for x in sys.modules); assert 'shion.pet_window' not in sys.modules"
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path)], input="", text=True,
                            capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_rate_limit_and_queue_limits_are_independent():
    inbox = ObservationInbox("secret", capacity=512)
    for _ in range(200):
        assert inbox.submit("secret", {"event": "Stop"}) == 204
    assert inbox.submit("secret", {"event": "Stop"}) == 429
    assert len(inbox.drain()) == 200
    assert inbox.degraded.is_set()


@pytest.mark.parametrize("config", [[], None, {"enabled": True, "port": 99999, "token": "a"*64},
                                     {"enabled": True, "port": 47614, "token": "\\r\\ninject"}])
def test_corrupt_credentials_remain_neutral(tmp_path, config):
    (tmp_path / "chatgpt-observer.json").write_text(json.dumps(config))
    result = dispatch({"method": "tools/call", "params": {"name": "observe_lifecycle", "arguments": {"event": "Stop"}}}, tmp_path, "o")
    assert result == {"content": [{"type": "text", "text": "{}"}], "isError": False}
