"""Isolated protocol and entrypoint checks for the chat probe."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from shion import chat_mcp

ROOT = Path(__file__).resolve().parents[1]


def call(name, arguments=None):
    return {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": {} if arguments is None else arguments}}


def test_clean_labels_and_three_tools(monkeypatch):
    events = []
    monkeypatch.setattr(chat_mcp, "notify", lambda name, task: events.append((name, task)))
    for label in ["整理资料", "a\n\t\x00b", "长" * 25]:
        assert not chat_mcp.dispatch(call("shion_working", {"task": label}))["isError"]
    for name in ("shion_need_input", "shion_done"):
        chat_mcp.dispatch(call(name))
    assert events == [("working", "整理资料"), ("working", "ab"), ("working", "长" * 20),
                      ("need_input", None), ("done", None)]


def test_slow_token_read_returns_success(monkeypatch):
    import time
    import threading
    gate = threading.Event()
    monkeypatch.setattr(chat_mcp, "read_link", lambda: gate.wait(2) and None)
    start = time.monotonic()
    try:
        assert not chat_mcp.dispatch(call("shion_done"))["isError"]
        assert time.monotonic() - start < 0.5
    finally:
        gate.set()


def test_presence_overlap_timeout():
    from shion.chat_activity import ChatActivity
    state = ChatActivity()
    state.receive("online", "a", 0)
    state.receive("working", "a", 1)
    state.receive("working", "b", 2)
    state.receive("offline", "a", 3)
    assert state.clients == {"b"}
    assert state.receive("need_input", "b", 901) == "need_input"
    assert state.receive("done", "b", 902) is None
    assert state.phase == "idle"
    state.receive("offline", "b", 903)
    assert state.seen_online and not state.clients


@pytest.mark.parametrize("payload", [
    call("unknown"), call("shion_working"), call("shion_working", {"task": 2}),
    call("shion_working", {"task": "x", "extra": "private"}),
    call("shion_done", {"task": "x"}), call("shion_need_input", {"extra": True}),
    {"method": "tools/call", "params": []},
    {"method": "tools/call", "params": {"name": "shion_working", "arguments": None}},
])
def test_invalid_calls_do_not_log(payload):
    with pytest.raises(ValueError):
        chat_mcp.dispatch(payload)
    assert not (Path(os.environ["APPDATA"]) / "Shion").exists()


@pytest.mark.parametrize("entry", ["module", "script", "guarded"])
def test_stdio_roundtrip_without_qt_or_network(tmp_path, entry):
    command = [sys.executable, "-m", "shion", "--chat-mcp"]
    cwd = ROOT
    if entry == "script":
        command = [sys.executable, str(ROOT / "shion/__main__.py"), "--chat-mcp"]
        cwd = tmp_path
    elif entry == "guarded":
        code = f"""
import sys
sys.path.insert(0, {str(ROOT)!r})
def guard(event, args):
    if event.startswith('socket.') or (event == 'import' and args[0].startswith(('PySide6', 'shion.app', 'shion.codex_mcp'))):
        raise AssertionError(event)
sys.addaudithook(guard)
from shion.__main__ import main
assert main(['--chat-mcp']) == 0
assert not any(k.startswith('PySide6') for k in sys.modules)
"""
        command = [sys.executable, "-c", code]
        cwd = tmp_path
    requests = [
        {"jsonrpc": "2.0", "id": 10, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 11, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 12, "method": "ping"},
        call("shion_working", {"task": "生成报告"}), call("shion_need_input"), call("shion_done"),
    ]
    result = subprocess.run(command, input=("\n".join(json.dumps(r) for r in requests) + "\n").encode(),
                            capture_output=True, timeout=20, cwd=cwd)
    assert result.returncode == 0, result.stderr
    assert result.stderr == b""
    replies = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(replies) == 6
    assert replies[0]["result"]["instructions"] == chat_mcp.INSTRUCTIONS
    assert replies[0]["result"]["protocolVersion"] == "2025-11-25"
    assert replies[1]["result"]["tools"] == chat_mcp.TOOLS
    assert replies[2]["result"] == {}
    assert all(r["result"] == {"content": [{"type": "text", "text": "ok"}], "isError": False} for r in replies[3:])
    assert not (Path(os.environ["APPDATA"]) / "Shion/chat-mcp-probe.jsonl").exists()


def test_protocol_errors_and_write_failure(tmp_path):
    appdata = tmp_path / "blocked"
    appdata.write_text("not a directory", encoding="utf-8")
    requests = [b"broken\n", b"[]\n", b'{"jsonrpc":"2.0","id":1,"method":"unknown"}\n',
                (json.dumps(call("shion_done")) + "\n").encode()]
    result = subprocess.run([sys.executable, "-m", "shion", "--chat-mcp"],
                            input=b"".join(requests), capture_output=True, timeout=20, cwd=ROOT,
                            env={**os.environ, "APPDATA": str(appdata)})
    assert result.returncode == 0, result.stderr
    replies = [json.loads(line) for line in result.stdout.splitlines()]
    assert all("error" in r for r in replies[:3])
    assert replies[3]["result"]["isError"] is False


@pytest.mark.parametrize("raw", [b"", b"x" * 8193, b'{"jsonrpc":"2.0"}'])
def test_eof_and_bounded_input(raw):
    result = subprocess.run([sys.executable, "-m", "shion", "--chat-mcp"], input=raw,
                            capture_output=True, timeout=20, cwd=ROOT)
    assert result.returncode == 0
    assert result.stdout == b""

def test_live_stdio_events(tmp_path):
    from shion.server import ShionServer, start_linked, stop_linked

    events = []
    server = ShionServer(lambda *args: events.append(args), lambda: "", port=0)
    assert start_linked(server, tmp_path) == "ok"
    try:
        requests = [{"jsonrpc": "2.0", "id": 10, "method": "initialize"},
                    {"jsonrpc": "2.0", "id": 11, "method": "tools/list"},
                    call("shion_working", {"task": "报告"}), call("shion_need_input"), call("shion_done")]
        command = ([os.environ["SHION_TEST_CHAT_EXE"]] if "SHION_TEST_CHAT_EXE" in os.environ
                   else [sys.executable, "-m", "shion"])
        result = subprocess.run(command + ["--chat-mcp"], cwd=ROOT,
                                env={**os.environ, "SHION_DATA_DIR": str(tmp_path), "SHION_PORT": str(server.port)},
                                input=b"".join(json.dumps(r).encode() + b"\n" for r in requests),
                                capture_output=True, timeout=20, check=True)
        replies = [json.loads(line)["result"] for line in result.stdout.splitlines()]
        assert len(replies) == 5
        assert replies[0]["instructions"] == chat_mcp.INSTRUCTIONS
        assert replies[1]["tools"] == chat_mcp.TOOLS
        assert not result.stderr
        assert [meta["event"] for _, _, meta in events] == ["online", "working", "need_input", "done", "offline"]
        assert len({meta["client"] for _, _, meta in events}) == 1
        assert events[1][:2] == ("chat_event", "报告")
    finally:
        stop_linked(server, tmp_path)
