"""v1.0.1：诗音没开时 hook 快速退出（命名管道探测）与连接失败熔断。

安全不变量：诗音没开 / 判断失败 / 熔断后，PermissionRequest 不输出 allow，PreToolUse 不输出 deny，
暂停检查点放行；SessionStart 仍然拉起诗音。
"""
import importlib.util
import io
import json
import os
import sys
import time
import urllib.error
import uuid
from pathlib import Path

import pytest

from shion.loopback import write_token

from shion import launcher

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "shion_hook.py"
windows_only = pytest.mark.skipif(os.name != "nt", reason="命名管道探测只在 Windows 上启用")


def load_hook():
    spec = importlib.util.spec_from_file_location("shion_hook_latency", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_main(h, monkeypatch, name, data=None):
    """在进程内跑一遍 main()，返回 stdout 里的内容。"""
    out = io.BytesIO()

    class Buffer:
        buffer = out

        def flush(self):
            pass

    monkeypatch.setattr(h.sys, "argv", [str(HOOK), name])
    monkeypatch.setattr(h, "read_input", lambda: data if data is not None else {})
    monkeypatch.setattr(h.sys, "stdout", Buffer())
    h.main()
    return out.getvalue()


def forbid_network(h, monkeypatch):
    calls = []

    def request(path, payload=None, timeout=0.5):
        calls.append(path)
        raise AssertionError(f"诗音没开时不该发请求：{path}")

    monkeypatch.setattr(h, "request", request)
    monkeypatch.setattr(h, "find_cc_process", lambda *a, **k: calls.append("find_cc_process"))
    return calls


PAYLOADS = {
    "PreToolUse": {"session_id": "s", "tool_name": "Read", "tool_input": {"file_path": "a.py"}},
    "PostToolUse": {"session_id": "s", "tool_name": "Read", "tool_input": {"file_path": "a.py"}},
    "PermissionRequest": {"session_id": "s", "tool_name": "Bash", "tool_input": {"command": "echo hi"}},
    "UserPromptSubmit": {"session_id": "s"},
    "PostToolUseFailure": {"session_id": "s", "tool_name": "Bash"},
    "Stop": {"session_id": "s"},
    "Notification": {"session_id": "s"},
}


def test_instance_name_constant_matches_the_app():
    from shion.app import INSTANCE_NAME

    assert INSTANCE_NAME is launcher.INSTANCE_NAME == "ShionDesktopPet-single-instance"


# ------------------------------------------------------------ shion_running()（实现在 shion/launcher.py，hook 共用）
def test_pipe_name_default_and_env_override(monkeypatch):
    h = launcher
    seen = []
    monkeypatch.setattr(h, "IS_WINDOWS", True)
    monkeypatch.setattr(h, "_wait_named_pipe", lambda path: seen.append(path) or (False, 2))
    monkeypatch.delenv("SHION_PORT", raising=False)
    monkeypatch.delenv("SHION_INSTANCE_NAME", raising=False)
    assert h.shion_running() is False
    monkeypatch.setenv("SHION_INSTANCE_NAME", "Custom-Name")
    assert h.shion_running() is False
    monkeypatch.setenv("SHION_INSTANCE_NAME", "")  # 空值等于没设
    assert h.shion_running() is False
    assert seen == ["\\\\.\\pipe\\ShionDesktopPet-single-instance", "\\\\.\\pipe\\Custom-Name",
                    "\\\\.\\pipe\\ShionDesktopPet-single-instance"]


@pytest.mark.parametrize("instance", [None, "Custom-Name"])
def test_custom_port_means_a_test_harness_so_it_is_uncertain(monkeypatch, instance):
    # 测试/冒烟脚本常用 SHION_PORT 指向一个没有命名管道的假服务器：不能因为没管道就丢事件。
    h = launcher
    monkeypatch.setattr(h, "IS_WINDOWS", True)
    monkeypatch.setattr(h, "_wait_named_pipe", lambda path: (_ for _ in ()).throw(AssertionError("不该探测")))
    monkeypatch.setenv("SHION_PORT", "5555")
    if instance:
        monkeypatch.setenv("SHION_INSTANCE_NAME", instance)
    else:
        monkeypatch.delenv("SHION_INSTANCE_NAME", raising=False)
    assert h.shion_running() is None


@pytest.mark.parametrize("result,expected", [
    ((True, 0), True),      # 管道存在
    ((False, 2), False),    # 没有这个管道：确定没开
    ((False, 121), None),   # 管道在但实例忙 / 超时：不确定
    ((False, 5), None),     # 其他错误：不确定
    ((False, 0), None),
])
def test_shion_running_results(monkeypatch, result, expected):
    h = launcher
    monkeypatch.setattr(h, "IS_WINDOWS", True)
    monkeypatch.setattr(h, "_wait_named_pipe", lambda path: result)
    monkeypatch.delenv("SHION_PORT", raising=False)
    assert h.shion_running() is expected


def test_shion_running_exception_and_non_windows_are_uncertain(monkeypatch):
    h = launcher
    monkeypatch.delenv("SHION_PORT", raising=False)
    monkeypatch.setattr(h, "IS_WINDOWS", True)
    monkeypatch.setattr(h, "_wait_named_pipe", lambda path: (_ for _ in ()).throw(OSError("boom")))
    assert h.shion_running() is None
    monkeypatch.setattr(h, "IS_WINDOWS", False)
    monkeypatch.setattr(h, "_wait_named_pipe", lambda path: (False, 2))
    assert h.shion_running() is None


@windows_only
def test_real_pipe_of_a_qt_local_server_is_detected(monkeypatch):
    from PySide6.QtNetwork import QLocalServer
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])  # 和其他测试一样用 QApplication，别留下 QCoreApplication
    name = "ShionHookTest-" + uuid.uuid4().hex[:12]
    monkeypatch.setenv("SHION_INSTANCE_NAME", name)
    monkeypatch.delenv("SHION_PORT", raising=False)
    h = launcher
    assert h.shion_running() is False
    server = QLocalServer()
    try:
        assert server.listen(name)
        assert h.shion_running() is True
    finally:
        server.close()
        app.processEvents()
    assert h.shion_running() is False


# ------------------------------------------------------------ 快速退出
@pytest.mark.parametrize("name", [n for n in PAYLOADS])
def test_not_running_exits_before_any_network_or_process_scan(monkeypatch, name):
    h = load_hook()
    calls = forbid_network(h, monkeypatch)
    monkeypatch.setattr(h, "shion_running", lambda: False)
    monkeypatch.setattr(h, "pause_gate", lambda *a, **k: calls.append("pause_gate"))
    t0 = time.monotonic()
    out = run_main(h, monkeypatch, name, PAYLOADS[name])
    assert out == b"" and calls == []
    assert time.monotonic() - t0 < 0.2


def test_session_start_still_ensures_running_when_pipe_is_missing(monkeypatch):
    h = load_hook()
    launched = []
    monkeypatch.setattr(h, "shion_running", lambda: False)
    monkeypatch.setattr(h, "ensure_running", lambda: launched.append("ensure"))
    monkeypatch.setattr(h, "request", lambda *a, **k: None)
    assert run_main(h, monkeypatch, "SessionStart", {"session_id": "s"}) == b""
    assert launched == ["ensure"]


@pytest.mark.parametrize("state", [None, True])
def test_uncertain_or_running_falls_back_to_original_flow(monkeypatch, state):
    h = load_hook()
    paths = []
    monkeypatch.setattr(h, "shion_running", lambda: state)
    monkeypatch.setattr(h, "find_cc_process", lambda *a, **k: None)
    monkeypatch.setattr(h, "request", lambda path, payload=None, timeout=0.5: paths.append(path) or None)
    monkeypatch.setattr(h, "pause_limit", lambda: 60)
    assert run_main(h, monkeypatch, "PreToolUse", PAYLOADS["PreToolUse"]) == b""
    assert paths == ["/pause/wait", "/event"]  # 宁可慢，不可误判


def test_probe_is_not_asked_for_unknown_events(monkeypatch):
    h = load_hook()
    monkeypatch.setattr(h, "shion_running", lambda: (_ for _ in ()).throw(AssertionError("不该探测")))
    assert run_main(h, monkeypatch, "NotAnEvent", {}) == b""


# ------------------------------------------------------------ 安全不变量
@pytest.mark.parametrize("scenario", ["not_running", "uncertain_and_down", "breaker_tripped"])
def test_safety_invariants_when_shion_is_unavailable(monkeypatch, scenario):
    h = load_hook()
    monkeypatch.setattr(h, "find_cc_process", lambda *a, **k: None)
    monkeypatch.setattr(h, "pause_limit", lambda: 60)
    monkeypatch.setattr(h, "permission_limit", lambda: 10)
    write_token(Path(os.environ["SHION_DATA_DIR"]), "a" * 64)  # 有令牌：真的去连，走连接失败 / 熔断分支
    if scenario == "not_running":
        monkeypatch.setattr(h, "shion_running", lambda: False)
    else:
        monkeypatch.setattr(h, "shion_running", lambda: None)
        monkeypatch.setenv("SHION_PORT", "1")  # 连不上
        monkeypatch.setattr(h, "TIMEOUT", 0.05)
        if scenario == "breaker_tripped":
            h.request("/health")
            assert h._down is True
    for name in ("PermissionRequest", "PreToolUse", "PostToolUse"):
        out = run_main(h, monkeypatch, name, PAYLOADS[name])
        assert out == b"", (scenario, name, out)  # 没有 allow、没有 deny、没有 continue=false
    assert h.pause_gate(60) is None  # 暂停检查点放行


# ------------------------------------------------------------ 熔断
def test_connection_failure_trips_breaker_and_later_requests_skip_the_network(monkeypatch):
    h = load_hook()
    attempts = []

    class Opener:
        def open(self, req, timeout=None):
            attempts.append(req.full_url)
            raise urllib.error.URLError(ConnectionRefusedError())

    monkeypatch.setattr(h.urllib.request, "build_opener", lambda *a: Opener())
    write_token(Path(os.environ["SHION_DATA_DIR"]), "a" * 64)
    assert h.request("/event", {}) is None and h._down is True
    assert h.request("/event", {}) is None and h.request("/pause/wait", {"wait": 0}) is None
    assert len(attempts) == 1


def test_http_errors_and_read_timeouts_do_not_trip_the_breaker(monkeypatch):
    h = load_hook()

    class Opener:
        def __init__(self, error):
            self.error = error

        def open(self, req, timeout=None):
            raise self.error

    for error in (urllib.error.HTTPError("http://x", 500, "boom", {}, None), TimeoutError("read"), ValueError("x")):
        monkeypatch.setattr(h.urllib.request, "build_opener", lambda *a, _e=error: Opener(_e))
        assert h.request("/event", {}) is None
        assert h._down is False


def test_breaker_state_is_per_process_not_sticky_across_hooks(monkeypatch):
    first = load_hook()
    first._down = True
    assert load_hook()._down is False


def test_long_polls_still_work_when_server_answers(monkeypatch):
    import threading
    from shion.remote import RemoteHub
    from shion.server import ShionServer

    hub = RemoteHub()
    srv = ShionServer(lambda t, d, m=None: None, lambda: "", port=0, hub=hub)
    srv.start()
    try:
        monkeypatch.setenv("SHION_PORT", str(srv.port))
        h = load_hook()
        assert h.request("/health")
        hub.pause()
        threading.Timer(0.3, hub.resume).start()
        answer = h.request("/pause/wait", {"wait": 5}, timeout=8)
        assert isinstance(answer, dict) and answer.get("paused") is not True
        assert h._down is False
    finally:
        hub.resume()
        srv.stop()


def test_ensure_running_probes_again_after_launch_even_if_breaker_tripped(monkeypatch):
    h = load_hook()
    monkeypatch.setenv("SHION_PORT", "1")
    launched, probes = [], []

    def request(path, payload=None, timeout=0.5):
        if h._down:
            return None
        probes.append(path)
        if len(probes) == 1:
            h._down = True  # 第一次探测：连接失败，熔断
            return None
        return {"ok": True} if launched and len(probes) >= 3 else (setattr(h, "_down", True) or None)

    monkeypatch.setattr(h, "request", request)
    monkeypatch.setattr(h, "launch_shion", lambda: launched.append(1))
    monkeypatch.setattr(h.time, "sleep", lambda s: None)
    h.ensure_running()
    assert launched == [1]
    assert len(probes) >= 3  # 熔断没有把启动后的轮询变成空转
