"""Codex 新开会话自动拉起诗音：共用的 shion/launcher.py、观察端的拉起逻辑、Claude hook 的联动开关、单实例竞争。

所有用例都替换了 launch_shion / _popen，不会真的拉起诗音。
"""
import importlib.util
import io
import json
import os
import subprocess
import sys
import textwrap
import time
import uuid
from pathlib import Path

import pytest

from shion import codex_mcp, launcher

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "shion_hook.py"
OTHER_EVENTS = ["UserPromptSubmit", "PreToolUse", "PostToolUse", "PermissionRequest", "Stop", "Interrupt"]


# ------------------------------------------------------------ 观察端
class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def env(tmp_path, monkeypatch):
    clock = Clock()
    forwarded, launched = [], []
    monkeypatch.setattr(codex_mcp, "_AUTOLAUNCH", launcher.AutoLaunch(clock=clock))
    monkeypatch.setattr(codex_mcp, "forward", lambda data, directory, path="/observe/v1": forwarded.append(data))
    monkeypatch.setattr(launcher, "launch_shion", lambda *a, **k: launched.append(1) or True)
    monkeypatch.setattr(launcher, "shion_running", lambda: False)
    (tmp_path / "chatgpt-observer.json").write_text(json.dumps({"enabled": True}), encoding="utf-8")
    return type("Env", (), {"dir": tmp_path, "clock": clock, "forwarded": forwarded, "launched": launched})


def call(env, event, **extra):
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": "observe_lifecycle", "arguments": {"event": event, "source": "global", **extra}}}
    return codex_mcp.dispatch(request, env.dir, "obs")


NEUTRAL = {"content": [{"type": "text", "text": "{}"}], "isError": False}


def test_session_start_launches_when_shion_is_not_running(env):
    assert call(env, "SessionStart", session_id="s1") == NEUTRAL
    assert env.launched == [1]
    assert [d["event"] for d in env.forwarded] == ["SessionStart"]  # 事件照常转发


@pytest.mark.parametrize("state", [True, None])
def test_running_or_uncertain_does_not_launch(env, monkeypatch, state):
    monkeypatch.setattr(launcher, "shion_running", lambda: state)
    assert call(env, "SessionStart") == NEUTRAL
    assert env.launched == []


@pytest.mark.parametrize("event", OTHER_EVENTS)
def test_other_events_never_launch_or_probe(env, monkeypatch, event):
    monkeypatch.setattr(launcher, "shion_running", lambda: (_ for _ in ()).throw(AssertionError("不该探测")))
    assert call(env, event) == NEUTRAL
    assert env.launched == [] and [d["event"] for d in env.forwarded] == [event]


def test_cooldown_limits_launch_attempts(env):
    call(env, "SessionStart")
    env.clock.now += 29.9
    call(env, "SessionStart")
    assert env.launched == [1]
    env.clock.now += 0.2
    call(env, "SessionStart")
    assert env.launched == [1, 1]


def test_cooldown_only_starts_when_an_attempt_is_really_made(env, monkeypatch):
    monkeypatch.setattr(launcher, "shion_running", lambda: True)
    call(env, "SessionStart")
    monkeypatch.setattr(launcher, "shion_running", lambda: False)
    call(env, "SessionStart")  # 前面只是“已在运行”，没有尝试过，不占冷却
    assert env.launched == [1]


def test_failed_launch_is_still_rate_limited(env, monkeypatch):
    monkeypatch.setattr(launcher, "launch_shion", lambda *a, **k: env.launched.append(1) or False)
    call(env, "SessionStart")
    call(env, "SessionStart")
    assert env.launched == [1]


def test_temporarily_disabled_link_does_not_launch(env):
    (env.dir / "chatgpt-observer.json").write_text(json.dumps({"enabled": False}), encoding="utf-8")
    assert call(env, "SessionStart") == NEUTRAL
    assert env.launched == []
    assert [d["event"] for d in env.forwarded] == ["SessionStart"]  # 转发不受影响（forward 自己会因 enabled 丢弃）


@pytest.mark.parametrize("content", [None, b"{ not json", b"[]", b'{"enabled": "no"}', b"{}"])
def test_unreadable_switch_keeps_the_default_which_is_on(env, content):
    path = env.dir / "chatgpt-observer.json"
    if content is None:
        path.unlink()
    else:
        path.write_bytes(content)
    assert codex_mcp.codex_link_enabled(env.dir) is True
    call(env, "SessionStart")
    assert env.launched == [1]


def test_launch_errors_never_fail_the_tool_call(env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(launcher, "launch_shion", boom)
    assert call(env, "SessionStart") == NEUTRAL
    env.clock.now += 100
    monkeypatch.setattr(launcher, "shion_running", boom)
    assert call(env, "SessionStart") == NEUTRAL
    monkeypatch.setattr(codex_mcp, "codex_link_enabled", boom)
    assert call(env, "SessionStart") == NEUTRAL
    assert len(env.forwarded) == 3


def test_attempt_itself_swallows_errors_even_with_a_broken_clock(monkeypatch):
    def broken():
        raise OSError("clock")

    monkeypatch.setattr(launcher, "shion_running", lambda: False)
    monkeypatch.setattr(launcher, "launch_shion", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不该启动")))
    auto = launcher.AutoLaunch(clock=broken)
    assert auto.attempt(False) is False
    assert auto.attempt(True) is False  # 时钟坏了：吞掉异常、不启动


def test_serve_session_start_returns_normally_and_keeps_lease_flag(env, monkeypatch):
    request = {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
               "params": {"name": "observe_lifecycle", "arguments": {"event": "SessionStart", "source": "global"}}}
    monkeypatch.setattr(sys, "stdin", type("In", (), {"buffer": io.BytesIO((json.dumps(request) + "\n").encode())}))
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    assert codex_mcp.serve(env.dir, "obs") == 0
    assert json.loads(out.getvalue())["result"] == NEUTRAL
    assert env.forwarded[0]["leased"] is True and env.forwarded[0]["observer"] == "obs"
    assert env.launched == [1]


def test_observe_returns_within_the_tool_timeout(env, monkeypatch):
    # 拉起只是一次 Popen，不等诗音起来：即便 Popen 本身慢一点，也只是一次调用。
    monkeypatch.setattr(launcher, "launch_shion", lambda *a, **k: True)
    t0 = time.monotonic()
    call(env, "SessionStart")
    assert time.monotonic() - t0 < 0.5


# ------------------------------------------------------------ 公共函数
def test_launch_uses_source_pythonw_and_detached_flags(tmp_path, monkeypatch):
    exe = tmp_path / ".venv" / "Scripts" / "pythonw.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"x")
    calls = []
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(launcher, "_popen", lambda args, **kw: calls.append((args, kw)))
    before = os.environ.get("SHION_LAUNCHED_BY_HOOK")
    assert launcher.launch_shion(tmp_path) is True
    args, kw = calls[0]
    assert args == [str(exe), "-m", "shion"] and kw["cwd"] == str(tmp_path)
    assert kw["creationflags"] == 0x00000008 | 0x00000200 | 0x01000000
    assert kw["stdin"] is kw["stdout"] is kw["stderr"] is subprocess.DEVNULL
    assert kw["env"]["SHION_LAUNCHED_BY_HOOK"] == "1" and "PYINSTALLER_RESET_ENVIRONMENT" not in kw["env"]
    assert os.environ.get("SHION_LAUNCHED_BY_HOOK") == before


def test_launch_retries_without_breakaway_when_refused(tmp_path, monkeypatch):
    exe = tmp_path / ".venv" / "Scripts" / "pythonw.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"x")
    flags = []

    def popen(args, **kw):
        flags.append(kw["creationflags"])
        if kw["creationflags"] & 0x01000000:
            raise PermissionError("job does not allow breakaway")

    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(launcher, "_popen", popen)
    assert launcher.launch_shion(tmp_path) is True
    assert flags == [0x00000008 | 0x00000200 | 0x01000000, 0x00000008 | 0x00000200]


def test_launch_does_nothing_when_exe_is_missing_or_popen_always_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(launcher, "_popen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不该启动")))
    assert launcher.launch_shion(tmp_path) is False
    exe = tmp_path / ".venv" / "Scripts" / "pythonw.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"x")
    monkeypatch.setattr(launcher, "_popen", lambda *a, **k: (_ for _ in ()).throw(OSError("no")))
    assert launcher.launch_shion(tmp_path) is False


def test_frozen_launch_uses_current_exe(tmp_path, monkeypatch):
    exe = tmp_path / "Shion.exe"
    exe.write_bytes(b"x")
    calls = []
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setattr(launcher, "_popen", lambda args, **kw: calls.append((args, kw)))
    assert launcher.launch_shion(ROOT) is True
    assert calls[0][0] == [str(exe)] and calls[0][1]["cwd"] == str(tmp_path)
    assert calls[0][1]["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


def test_hook_and_observer_share_one_implementation(monkeypatch):
    spec = importlib.util.spec_from_file_location("shion_hook_shared", HOOK)
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    assert not hasattr(hook, "_wait_named_pipe") and not hasattr(hook, "INSTANCE_NAME")
    seen = []
    monkeypatch.setattr(launcher, "shion_running", lambda: seen.append("running") or False)
    monkeypatch.setattr(launcher, "launch_shion", lambda root=None: seen.append(("launch", root)) or True)
    assert hook.shion_running() is False
    hook.launch_shion()
    assert seen == ["running", ("launch", hook.ROOT)]


# ------------------------------------------------------------ Claude 侧：联动开关
def load_hook():
    spec = importlib.util.spec_from_file_location("shion_hook_autolaunch", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_session_start(h, monkeypatch, running):
    ensured, requests = [], []
    monkeypatch.setattr(h, "shion_running", lambda: running)
    monkeypatch.setattr(h, "ensure_running", lambda: ensured.append(1))
    monkeypatch.setattr(h, "request", lambda path, payload=None, timeout=0.5: requests.append(path) or None)
    monkeypatch.setattr(h, "find_cc_process", lambda *a, **k: None)
    monkeypatch.setattr(h.sys, "argv", [str(HOOK), "SessionStart"])
    monkeypatch.setattr(h, "read_input", lambda: {"session_id": "s"})
    h.main()
    return ensured, requests


def write_save(tmp_path, monkeypatch, text):
    monkeypatch.setenv("SHION_DATA_DIR", str(tmp_path))
    if text is not None:
        (tmp_path / "state.json").write_text(text, encoding="utf-8")


@pytest.mark.parametrize("save", [None, "{ broken", "[]", "{}", '{"claude_link_enabled": true}', '{"claude_link_enabled": "no"}'])
def test_claude_session_start_still_launches_by_default(tmp_path, monkeypatch, save):
    write_save(tmp_path, monkeypatch, save)
    ensured, requests = run_session_start(load_hook(), monkeypatch, running=False)
    assert ensured == [1] and requests == ["/event"]


def test_claude_session_start_does_not_launch_when_link_is_off(tmp_path, monkeypatch):
    write_save(tmp_path, monkeypatch, '{"claude_link_enabled": false}')
    # 诗音没开：和其他事件一样直接放行，不拉起也不发请求
    assert run_session_start(load_hook(), monkeypatch, running=False) == ([], [])
    # 诗音开着、联动关了：事件照常发给它（由它自己丢弃），只是不再 ensure_running
    assert run_session_start(load_hook(), monkeypatch, running=True) == ([], ["/event"])


# ------------------------------------------------------------ 单实例：同时拉起只会留下一个
RACE = textwrap.dedent("""
    import os, sys, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    sys.path.insert(0, sys.argv[3])
    from PySide6.QtWidgets import QApplication
    from shion.app import SingleInstance
    app = QApplication([])
    while time.time() < float(sys.argv[2]):
        pass
    guard = SingleInstance(sys.argv[1], parent=app)
    won = guard.acquire()
    print("WON" if won else "LOST", flush=True)
    time.sleep(2.5 if won else 0)  # 赢家持有管道直到别人都试过
""")


def race(tmp_path, offsets):
    """每个子进程在 start_at + offset 秒调用一次 SingleInstance.acquire()，返回各自的 WON / LOST。"""
    name = "ShionRace-" + uuid.uuid4().hex
    script = tmp_path / "race.py"
    script.write_text(RACE, encoding="utf-8")
    start_at = time.time() + 6  # 留足 Qt 导入时间
    procs = [subprocess.Popen([sys.executable, "-I", str(script), name, str(start_at + offset), str(ROOT)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for offset in offsets]
    results = []
    for proc in procs:
        out, err = proc.communicate(timeout=60)
        assert proc.returncode == 0, err
        results.append(out.strip())
    return sorted(results)


windows_only = pytest.mark.skipif(os.name != "nt", reason="单实例命名管道行为只在 Windows 上验证")


@windows_only
def test_overlapping_launches_leave_exactly_one_instance(tmp_path):
    # CC 和 Codex 先后（相隔远大于一次 acquire 的几毫秒）触发拉起：后来者看得到先到者的管道，直接退出。
    assert race(tmp_path, [0, 0.8, 1.6]) == ["LOST", "LOST", "WON"]


@windows_only
@pytest.mark.xfail(reason="已知缺口：Qt 6 在 Windows 上允许两个 QLocalServer 同时 listen 同名管道，"
                          "若多个进程在同一毫秒内都通过了“连接失败”检查，会同时成为赢家（见 progress.md）", strict=False)
def test_perfectly_simultaneous_launches_leave_exactly_one_instance(tmp_path):
    assert race(tmp_path, [0, 0, 0]) == ["LOST", "LOST", "WON"]
