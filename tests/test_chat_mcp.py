"""Isolated protocol and entrypoint checks for the chat probe."""
from datetime import datetime
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


def records():
    path = Path(os.environ["APPDATA"]) / "Shion/chat-mcp-probe.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_raw_labels_and_three_tools():
    labels = ["整理资料", "a\n\t\x00b", "长" * 25]
    for label in labels:
        assert chat_mcp.dispatch(call("shion_working", {"task": label}))["content"][0]["text"] == "ok"
    for name in ("shion_need_input", "shion_done"):
        chat_mcp.dispatch(call(name))
    rows = records()
    assert [row["task"] for row in rows] == labels + [None, None]
    assert [row["tool"] for row in rows] == ["shion_working"] * 3 + ["shion_need_input", "shion_done"]
    assert all(set(row) == {"tool", "time", "task"} for row in rows)
    assert all(datetime.fromisoformat(row["time"]).tzinfo for row in rows)


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
    assert len(records()) == 3


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
    assert replies[3]["result"]["isError"] is True
    assert "ok" not in result.stdout.decode()


@pytest.mark.parametrize("raw", [b"", b"x" * 8193, b'{"jsonrpc":"2.0"}'])
def test_eof_and_bounded_input(raw):
    result = subprocess.run([sys.executable, "-m", "shion", "--chat-mcp"], input=raw,
                            capture_output=True, timeout=20, cwd=ROOT)
    assert result.returncode == 0
    assert result.stdout == b""
