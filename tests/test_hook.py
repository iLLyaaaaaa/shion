import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from shion.server import ShionServer

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "shion_hook.py"
PRAISE_LINE = "[诗音] 用户觉得你刚才做得很好。"


@pytest.fixture
def env(tmp_path):
    events, state = [], {"praise": 0}

    def take():
        n, state["praise"] = state["praise"], 0
        return n

    srv = ShionServer(lambda t, d: events.append((t, d)), take, port=0)
    srv.start()
    yield srv, events, state, tmp_path
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
    state["praise"] = 2
    r = run_hook("SessionStart", srv.port, tmp)
    assert r.returncode == 0 and r.stdout == b""
    assert events == [("session_start", None)]
    assert state["praise"] == 2  # 只有 UserPromptSubmit 才取夸奖


def test_unknown_event_sends_nothing(env):
    srv, events, _, tmp = env
    r = run_hook("Bogus", srv.port, tmp)
    assert r.returncode == 0 and events == []
    assert run_hook("", srv.port, tmp).returncode == 0


def test_prompt_injects_praise_utf8(env):
    srv, events, state, tmp = env
    state["praise"] = 2
    r = run_hook("UserPromptSubmit", srv.port, tmp)
    assert r.returncode == 0
    assert r.stdout.decode("utf-8").strip() == PRAISE_LINE
    assert events == [("prompt", None)]
    assert state["praise"] == 0  # 已取走
    assert run_hook("UserPromptSubmit", srv.port, tmp).stdout == b""


def test_prompt_respects_inject_praise_false(env):
    srv, _, state, tmp = env
    (tmp / "state.json").write_text(json.dumps({"inject_praise": False}), encoding="utf-8")
    state["praise"] = 2
    r = run_hook("UserPromptSubmit", srv.port, tmp)
    assert r.returncode == 0 and r.stdout == b""
    assert state["praise"] == 0  # 计数仍被清零


def test_prompt_with_corrupt_save_still_injects(env):
    srv, _, state, tmp = env
    (tmp / "state.json").write_text("{坏的", encoding="utf-8")
    state["praise"] = 2
    assert run_hook("UserPromptSubmit", srv.port, tmp).stdout.decode("utf-8").strip() == PRAISE_LINE


@pytest.mark.parametrize("lang", ["zh", "en", "ja"])
@pytest.mark.parametrize("count", [1, 9])
def test_praise_is_one_localized_sentence_without_count(env, lang, count):
    from shion.lines import Lines
    srv, _, state, tmp = env
    (tmp / "state.json").write_text(json.dumps({"language": lang}), encoding="utf-8")
    state["praise"] = count
    r = run_hook("UserPromptSubmit", srv.port, tmp)
    assert r.returncode == 0 and r.stderr == b""
    assert r.stdout.decode("utf-8") == Lines(lang).ui("hook_praise") + "\n"
    assert state["praise"] == 0


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
