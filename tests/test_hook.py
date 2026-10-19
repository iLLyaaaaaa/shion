import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from shion.remote import RemoteHub
from shion.server import ShionServer

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "shion_hook.py"
PRAISE_LINE = "[诗音] 用户觉得你刚才做得很好。"


@pytest.fixture
def env(tmp_path):
    events, state = [], {"feedback": ""}

    def take():
        text, state["feedback"] = state["feedback"], ""
        return text

    hub = RemoteHub()
    srv = ShionServer(lambda t, d: events.append((t, d)), take, port=0, hub=hub)
    srv.start()
    yield srv, events, state, tmp_path
    hub.resume()
    srv.stop()


def run_hook(name, port, data_dir, stdin=b"{}"):
    e = {**os.environ, "SHION_PORT": str(port), "SHION_DATA_DIR": str(data_dir)}
    return subprocess.run(
        [sys.executable, str(HOOK), name], input=stdin, capture_output=True, env=e, timeout=20
    )


@pytest.mark.parametrize(
    "name,etype",
    [("Notification", "notification"), ("PostToolUseFailure", "tool_error")],
)
def test_forward_events(env, name, etype):
    srv, events, _, tmp = env
    r = run_hook(name, srv.port, tmp)
    assert r.returncode == 0 and r.stdout == b"" and r.stderr == b""
    assert events == [(etype, None)]


def load_hook():
    import importlib.util

    spec = importlib.util.spec_from_file_location("shion_hook_mod", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_describe_tool():
    h = load_hook()
    assert h.describe_tool("Read", {"file_path": r"D:\a b\state.py"}) == {"tool": "read", "target": "state.py"}
    assert h.describe_tool("Edit", {"file_path": "src/x/bubble.py", "old_string": "秘密"}) == {"tool": "edit", "target": "bubble.py"}
    assert h.describe_tool("Write", {"file_path": "a.txt", "content": "秘密"})["target"] == "a.txt"
    assert h.describe_tool("Bash", {"command": "rm -rf secret"}) == {"tool": "bash", "target": ""}
    assert h.describe_tool("Grep", {"pattern": "x" * 50})["target"] == "x" * 19 + "…"
    assert h.describe_tool("WebFetch", {"url": "https://x.com/a?token=1"}) == {"tool": "web", "target": "x.com"}
    assert h.describe_tool("Agent", {"description": "查日志"}) == {"tool": "agent", "target": "查日志"}
    assert h.describe_tool("Weird", None) == {"tool": "other", "target": ""}
    assert h.describe_tool("Read", "not a dict") == {"tool": "read", "target": ""}


def test_first_sentence():
    h = load_hook()
    assert h.first_sentence("## 做完啦！改了3个文件。\n其他") == "做完啦"
    assert h.first_sentence("Done. All good") == "Done"
    assert h.first_sentence("\n\n**好**的，已经处理完毕") == "好的，已经处理完毕"
    assert h.first_sentence("v1.2 ok") == "v1.2 ok"
    long = h.first_sentence("很长" * 50)
    assert len(long) == 40 and long.endswith("…")
    assert h.first_sentence(None) == "" and h.first_sentence("   \n ") == ""


def test_pretooluse_sends_json_detail(env):
    srv, events, _, tmp = env
    payload = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "C:/p/state.py"}}).encode()
    r = run_hook("PreToolUse", srv.port, tmp, stdin=payload)
    assert r.returncode == 0 and r.stdout == b""
    assert events[0][0] == "working"
    assert json.loads(events[0][1]) == {"tool": "read", "target": "state.py"}


def test_pretooluse_bad_stdin_still_sends_working(env):
    srv, events, _, tmp = env
    run_hook("PreToolUse", srv.port, tmp, stdin=b"not json")
    assert events[0][0] == "working" and json.loads(events[0][1])["tool"] == "other"


def test_stop_sends_first_sentence(env):
    srv, events, _, tmp = env
    payload = json.dumps({"last_assistant_message": "## 改好了。后面还有很多"}, ensure_ascii=False).encode("utf-8")
    run_hook("Stop", srv.port, tmp, stdin=payload)
    assert events == [("stop", "改好了")]
    events.clear()
    run_hook("Stop", srv.port, tmp, stdin=b"{}")
    assert events == [("stop", None)]


def test_tool_error_sends_tool_name_but_not_interrupts(env):
    srv, events, _, tmp = env
    run_hook("PostToolUseFailure", srv.port, tmp, stdin=json.dumps({"tool_name": "Bash", "error": "Exit code 1"}).encode())
    run_hook("PostToolUseFailure", srv.port, tmp, stdin=json.dumps({"tool_name": "Bash", "is_interrupt": True}).encode())
    assert events == [("tool_error", "Bash")]


def test_session_start_forwards_and_prints_nothing(env):
    srv, events, state, tmp = env
    state["feedback"] = PRAISE_LINE
    r = run_hook("SessionStart", srv.port, tmp)
    assert r.returncode == 0 and r.stdout == b""
    assert events == [("session_start", None)]
    assert state["feedback"] == PRAISE_LINE  # 只有 UserPromptSubmit / PostToolUse 才取反馈


def test_unknown_event_sends_nothing(env):
    srv, events, _, tmp = env
    r = run_hook("Bogus", srv.port, tmp)
    assert r.returncode == 0 and events == []
    assert run_hook("", srv.port, tmp).returncode == 0


def test_prompt_injects_feedback_utf8(env):
    srv, events, state, tmp = env
    state["feedback"] = PRAISE_LINE
    r = run_hook("UserPromptSubmit", srv.port, tmp)
    assert r.returncode == 0
    assert r.stdout.decode("utf-8").strip() == PRAISE_LINE
    assert events == [("prompt", None)]
    assert state["feedback"] == ""  # 已取走
    assert run_hook("UserPromptSubmit", srv.port, tmp).stdout == b""


def test_prompt_with_corrupt_save_still_injects(env):
    srv, _, state, tmp = env
    (tmp / "state.json").write_text("{坏的", encoding="utf-8")
    state["feedback"] = PRAISE_LINE
    assert run_hook("UserPromptSubmit", srv.port, tmp).stdout.decode("utf-8").strip() == PRAISE_LINE


def test_post_tool_use_delivers_feedback_as_additional_context(env):
    srv, events, state, tmp = env
    state["feedback"] = "[诗音] 用户认为刚才的改动有问题：不对。请重新检查。"
    r = run_hook("PostToolUse", srv.port, tmp)
    assert r.returncode == 0 and r.stderr == b""
    out = json.loads(r.stdout.decode("utf-8"))
    assert out == {"hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": "[诗音] 用户认为刚才的改动有问题：不对。请重新检查。",
    }}
    assert events == [] and state["feedback"] == ""
    assert run_hook("PostToolUse", srv.port, tmp).stdout == b""  # 没有反馈就什么都不输出


def test_feedback_hooks_are_silent_when_shion_is_not_running(tmp_path):
    for name in ("PostToolUse", "UserPromptSubmit"):
        r = run_hook(name, 1, tmp_path)  # 端口 1：连不上
        assert r.returncode == 0 and r.stdout == b"" and r.stderr == b""


# ---------------------------------------------------------------- 暂停 / 继续
def test_pre_tool_use_passes_straight_through_when_not_paused(env):
    srv, events, _, tmp = env
    r = run_hook("PreToolUse", srv.port, tmp, stdin=json.dumps({"tool_name": "Read"}).encode())
    assert r.returncode == 0 and r.stdout == b""
    assert events and events[0][0] == "working"


def test_pre_tool_use_passes_when_shion_is_not_running(tmp_path):
    t0 = time.monotonic()
    r = run_hook("PreToolUse", 1, tmp_path)
    assert r.returncode == 0 and r.stdout == b"" and r.stderr == b""
    assert time.monotonic() - t0 < 10


def test_pre_tool_use_waits_while_paused_and_continues_on_resume(env):
    srv, events, _, tmp = env
    srv.hub.pause()
    threading.Timer(1.0, srv.hub.resume).start()
    t0 = time.monotonic()
    r = run_hook("PreToolUse", srv.port, tmp, stdin=json.dumps({"tool_name": "Read"}).encode())
    assert time.monotonic() - t0 >= 0.9  # 真的被挡住了
    assert r.returncode == 0 and r.stdout == b""  # 放行：没有 deny
    assert events and events[0][0] == "working"


def test_prompt_event_releases_pause_from_the_server_thread(env):
    srv, events, _, tmp = env
    srv.hub.pause()
    proc = subprocess.Popen(
        [sys.executable, str(HOOK), "PreToolUse"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        env={**os.environ, "SHION_PORT": str(srv.port), "SHION_DATA_DIR": str(tmp)},
    )
    proc.stdin.write(b"{}")
    proc.stdin.close()
    time.sleep(1.0)
    assert proc.poll() is None  # 还在等
    run_hook("UserPromptSubmit", srv.port, tmp)
    assert proc.wait(timeout=10) == 0 and proc.stdout.read() == b""
    assert srv.hub.is_paused is False


def test_pause_gate_times_out_with_deny_and_reports_it(env, monkeypatch):
    srv, events, _, tmp = env
    monkeypatch.setenv("SHION_PORT", str(srv.port))
    h = load_hook()
    srv.hub.pause()
    reason = h.pause_gate(0.5, poll=0.2)
    assert reason == "用户暂停了工作，请停下并等待用户指示"
    assert ("pause_timeout", None) in events


def test_pre_tool_use_prints_deny_json_after_pause_timeout(env):
    srv, events, _, tmp = env
    srv.hub.pause()
    code = (
        "import sys, importlib.util;"
        f"spec = importlib.util.spec_from_file_location('h', {str(HOOK)!r});"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m);"
        "m.pause_limit = lambda: 1; sys.argv = ['x', 'PreToolUse']; m.main()"
    )
    r = subprocess.run(
        [sys.executable, "-c", code], input=b"{}", capture_output=True, timeout=20,
        env={**os.environ, "SHION_PORT": str(srv.port), "SHION_DATA_DIR": str(tmp)},
    )
    out = json.loads(r.stdout.decode("utf-8"))
    assert out == {"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": "用户暂停了工作，请停下并等待用户指示",
    }}
    assert ("pause_timeout", None) in events
    assert not any(t == "working" for t, _ in events)  # 被拒绝的这次不算开工


def test_pause_gate_bad_server_response_means_no_pause(monkeypatch):
    h = load_hook()
    for bad in (None, [], {"paused": "yes"}, {"paused": 1}, {}):
        monkeypatch.setattr(h, "request", lambda *a, _bad=bad, **k: _bad)
        assert h.pause_gate(5, poll=0.1) is None


def test_pause_limit_comes_from_save_and_is_clamped(tmp_path, monkeypatch):
    monkeypatch.setenv("SHION_DATA_DIR", str(tmp_path))
    h = load_hook()
    assert h.pause_limit() == 1800
    for value, expected in ((600, 600), (5, 60), (99999, 1880), ("x", 1800), (True, 1800)):
        (tmp_path / "state.json").write_text(json.dumps({"remote": {"pause_timeout": value}}), encoding="utf-8")
        assert h.pause_limit() == expected


def test_launch_sets_source_only_on_child_environment(monkeypatch):
    h = load_hook()
    calls = []
    before = os.environ.get("SHION_LAUNCHED_BY_HOOK")
    monkeypatch.setattr(h.subprocess, "Popen", lambda *args, **kwargs: calls.append((args, kwargs)))
    h.launch_shion()
    assert len(calls) == 1
    assert calls[0][1]["env"]["SHION_LAUNCHED_BY_HOOK"] == "1"
    assert os.environ.get("SHION_LAUNCHED_BY_HOOK") == before


def test_server_down_is_silent_and_fast(tmp_path):
    for name in ("PreToolUse", "Stop", "Notification", "UserPromptSubmit"):
        t0 = time.monotonic()
        r = run_hook(name, 1, tmp_path)  # 端口 1：连不上
        assert r.returncode == 0 and r.stdout == b"" and r.stderr == b""
        assert time.monotonic() - t0 < 3


def test_large_stdin_is_drained(env):
    srv, events, _, tmp = env
    big = json.dumps({"x": "a" * 2_000_000}).encode()
    r = run_hook("Stop", srv.port, tmp, stdin=big)
    assert r.returncode == 0 and events == [("stop", None)]


def test_session_start_running_server_does_not_launch(env, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("shion_hook", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setenv("SHION_PORT", str(env[0].port))
    launched = []
    monkeypatch.setattr(mod, "launch_shion", lambda: launched.append(1))
    mod.ensure_running()
    assert launched == []


def test_session_start_launches_when_down(monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("shion_hook", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setenv("SHION_PORT", "1")
    launched = []
    monkeypatch.setattr(mod, "launch_shion", lambda: launched.append(1))
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    t = iter(range(0, 1000, 2))
    monkeypatch.setattr(mod.time, "monotonic", lambda: next(t))
    mod.ensure_running()
    assert launched == [1]


def test_hanging_server_returns_quickly(tmp_path):
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(5)  # 接受连接但永远不回包
    try:
        t0 = time.monotonic()
        r = run_hook("Stop", s.getsockname()[1], tmp_path)
        assert r.returncode == 0 and r.stdout == b""
        assert time.monotonic() - t0 < 5
    finally:
        s.close()


def test_first_sentence_keeps_underscores():
    assert load_hook().first_sentence("读取 does_not_exist.md 失败") == "读取 does_not_exist.md 失败"


def test_describe_tool_caps_target_length():
    h = load_hook()
    assert len(h.describe_tool("Read", {"file_path": "a/" + "x" * 500})["target"]) == 60
