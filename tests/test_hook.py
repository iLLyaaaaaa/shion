import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from shion.server import ShionServer

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "shion_hook.py"
PRAISE_LINE = (
    "[Shion 桌宠] 自你上次回复后，用户通过摸 Shion 的头表扬了你 2 次。可以自然地回应，不必刻意。"
)


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
    [("PreToolUse", "working"), ("Stop", "stop"), ("Notification", "notification")],
)
def test_forward_events(env, name, etype):
    srv, events, _, tmp = env
    r = run_hook(name, srv.port, tmp)
    assert r.returncode == 0 and r.stdout == b"" and r.stderr == b""
    assert events == [(etype, None)]


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
