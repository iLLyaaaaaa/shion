"""立即中断、按会话区分的工作状态、工具执行中保持 working。"""
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import timedelta

import pytest

from shion import interrupt, winproc
from shion.remote import RemoteHub
from shion.server import ShionServer, parse_meta
from shion.state import Config, PetState, SaveData
from tests.test_controller import T0, env, qapp, find_action  # noqa: F401
from tests.test_hook import HOOK, run_hook
from tests.test_stop_work import join, start_waiters

INTERRUPTED = "已经中断啦，在 CC 里说一声就能继续"
NO_PROCESS = "找不到正在工作的进程，先改成普通的停下啦"


def sec(n):
    return timedelta(seconds=n)


def ft(unix: float) -> int:
    """Unix 秒 → FILETIME。"""
    return int(unix * 1e7) + winproc.EPOCH_DIFF


# ---------------------------------------------------------------- 状态机：会话与 working
@pytest.fixture
def pet():
    return PetState(SaveData(), T0)


def test_tool_in_flight_keeps_working_up_to_30_minutes(pet):
    pet.claude_event("working", None, T0, "s1", "t1")
    assert pet.current(T0 + sec(29 * 60)) == "working"  # 远超过 5 分钟：工具还在跑
    pet.tick(T0 + sec(29 * 60))
    assert pet.current(T0 + sec(30 * 60 + 1)) != "working"  # 上限 30 分钟


def test_after_tool_done_working_lasts_5_minutes(pet):
    pet.claude_event("working", None, T0, "s1", "t1")
    pet.claude_event("tool_done", None, T0 + sec(400), "s1", "t1")
    assert pet.current(T0 + sec(400 + 299)) == "working"
    assert pet.current(T0 + sec(400 + 301)) == "idle"


def test_tool_error_also_ends_the_tool(pet):
    pet.claude_event("working", None, T0, "s1", "t1")
    pet.claude_event("tool_error", "Bash", T0 + sec(10), "s1", "t1")
    assert pet.tool_starts("s1") == []
    assert pet.current(T0 + sec(10 + 301)) != "working"


def test_debug_mode_leaves_working_after_60_seconds_without_tools():
    pet = PetState(SaveData(), T0, Config.debug())
    pet.claude_event("working", None, T0, "s1", "t1")
    assert pet.current(T0 + sec(120)) == "working"  # 工具执行中
    pet.claude_event("tool_done", None, T0 + sec(120), "s1", "t1")
    assert pet.current(T0 + sec(179)) == "working"
    assert pet.current(T0 + sec(181)) != "working"


def test_prompt_starts_working(pet):
    pet.claude_event("prompt", None, T0, "s1")
    assert pet.current(T0) == "working" and pet.working_sessions(T0) == ["s1"]


def test_tool_done_without_session_does_not_start_working(pet):
    pet.claude_event("tool_done", None, T0, "s1", "t1")
    pet.claude_event("tool_error", "Bash", T0, "s2")
    assert not pet.is_working(T0)


def test_stop_of_one_session_returns_to_working_if_another_works(pet):
    pet.claude_event("working", None, T0, "a", "t1")
    pet.claude_event("working", None, T0, "b", "t2")
    r = pet.claude_event("stop", None, T0 + sec(1), "a")
    assert "claude_done" in [x.key for x in r]
    assert pet.current(T0 + sec(2)) == "done"
    assert pet.current(T0 + sec(5)) == "working"  # b 还在工作
    assert pet.save.stats["claude_tasks"] == 1
    pet.claude_event("stop", None, T0 + sec(6), "b")
    assert pet.current(T0 + sec(10)) == "idle" and pet.save.stats["claude_tasks"] == 2


def test_second_session_starting_does_not_repeat_working_line(pet):
    assert "claude_working" in [x.key for x in pet.claude_event("working", None, T0, "a", "t1")]
    assert "claude_working" not in [x.key for x in pet.claude_event("working", None, T0, "b", "t2")]


def test_end_session_does_not_count_a_task(pet):
    pet.claude_event("working", None, T0, "a", "t1")
    pet.end_session("a")
    assert not pet.is_working(T0) and pet.save.stats["claude_tasks"] == 0


# ---------------------------------------------------------------- hub：一次性中断标记
def test_interrupt_flag_stops_next_checkpoint_once_and_only_for_that_session():
    hub = RemoteHub()
    hub.request_interrupt(["a"])
    assert hub.wait_gate(0, "b") == (False, False)
    assert hub.wait_gate(0, None) == (False, False)
    assert hub.wait_gate(0, "a") == (False, True)
    assert hub.wait_gate(0, "a") == (False, False)


def test_interrupt_releases_a_hook_waiting_at_a_stop():
    hub = RemoteHub()
    hub.pause()
    results = []
    t = threading.Thread(target=lambda: results.append(hub.wait_gate(5, "a")), daemon=True)
    t.start()
    deadline = time.monotonic() + 3
    while hub._holding < 1 and time.monotonic() < deadline:
        time.sleep(0.01)
    hub.request_interrupt(["a"])
    t.join(5)
    assert results == [(True, True)]
    hub.resume()


def test_clear_interrupt():
    hub = RemoteHub()
    hub.request_interrupt(["a"])
    hub.clear_interrupt("a")
    assert not hub.interrupt_pending("a") and hub.wait_gate(0, "a") == (False, False)


# ---------------------------------------------------------------- HTTP 服务：会话字段
def _post(port, path, body):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


@pytest.fixture
def srv():
    events = []
    hub = RemoteHub()
    server = ShionServer(lambda t, d, m=None: events.append((t, d, m)), lambda: "", port=0, hub=hub)
    server.start()
    yield server, hub, events
    hub.resume()
    server.stop()


PROC = {"pid": 1234, "created": 99, "name": "claude.exe", "entry": "cli", "hooks": [5, 6]}


def test_meta_is_validated_and_forwarded(srv):
    server, _, events = srv
    _post(server.port, "/event", {"type": "working", "session": "s1", "tool_id": "t1", "proc": PROC})
    assert events == [("working", None, {"session": "s1", "tool_id": "t1", "proc": PROC})]
    _post(server.port, "/event", {"type": "stop"})
    assert events[-1] == ("stop", None, None)  # 没带会话：旧的两参数回调


@pytest.mark.parametrize("bad", [
    {"session": 3}, {"session": ""}, {"session": "x" * 200}, {"tool_id": []},
    {"proc": {**PROC, "name": "cmd.exe"}}, {"proc": {**PROC, "pid": -1}}, {"proc": {**PROC, "pid": True}},
    {"proc": {**PROC, "hooks": ["a"]}}, {"proc": {**PROC, "hooks": list(range(1, 20))}}, {"proc": "x"},
])
def test_bad_meta_is_rejected(srv, bad):
    server, _, events = srv
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(server.port, "/event", {"type": "working", **bad})
    assert e.value.code == 400 and events == []


def test_parse_meta_lowercases_process_name():
    assert parse_meta({"proc": {**PROC, "name": "Claude.EXE"}})["proc"]["name"] == "claude.exe"


def test_pause_wait_with_session_reports_interrupt_and_notifies(srv):
    server, hub, events = srv
    hub.request_interrupt(["s1"])
    assert _post(server.port, "/pause/wait", {"wait": 0, "session": "s2"}) == {"paused": False, "stop": False}
    assert _post(server.port, "/pause/wait", {"wait": 0, "session": "s1"}) == {"paused": False, "stop": True}
    assert events == [("work_stopped", None, {"session": "s1"})]


@pytest.mark.parametrize("etype", ["prompt", "stop"])
def test_prompt_or_stop_clears_unused_interrupt(srv, etype):
    server, hub, _ = srv
    hub.request_interrupt(["s1"])
    _post(server.port, "/event", {"type": etype, "session": "s1"})
    assert not hub.interrupt_pending("s1")


def test_http_cannot_request_an_interrupt(srv):
    server, hub, _ = srv
    for path in ("/pause/wait", "/event", "/feedback/take", "/permission/wait"):
        for body in ({"interrupt": True, "session": "s1"}, {"type": "interrupt", "session": "s1"},
                     {"type": "work_stopped", "session": "s1"}):
            try:
                _post(server.port, path, body)
            except urllib.error.HTTPError:
                pass
    assert not hub.interrupt_pending("s1")


# ---------------------------------------------------------------- hook：会话与 CC 进程
def load_hook():
    spec = importlib.util.spec_from_file_location("shion_hook_t", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TABLE = {10: (1, "explorer.exe"), 20: (10, "WindowsTerminal.exe"), 30: (20, "claude.exe"),
         40: (30, "python.exe"), 50: (40, "python.exe"), 1: (0, "System")}


def test_find_cc_process_follows_the_real_parent_chain():
    h = load_hook()
    got = h.find_cc_process(TABLE, me=50, claude_pid=30, created=lambda pid: 777)
    assert got["pid"] == 30 and got["created"] == 777 and got["name"] == "claude.exe"
    assert got["hooks"] == [50, 40]


def test_find_cc_process_requires_claude_pid_on_the_chain():
    h = load_hook()
    assert h.find_cc_process(TABLE, me=50, claude_pid=999, created=lambda pid: 777) is None


def test_find_cc_process_without_env_takes_nearest_cc_ancestor(monkeypatch):
    h = load_hook()
    monkeypatch.delenv("CLAUDE_PID", raising=False)
    assert h.find_cc_process(TABLE, me=50, created=lambda pid: 777)["pid"] == 30
    assert h.find_cc_process({50: (40, "python.exe"), 40: (1, "cmd.exe"), 1: (0, "x")}, me=50,
                             created=lambda pid: 777) is None
    assert h.find_cc_process(TABLE, me=50, created=lambda pid: None) is None  # 拿不到创建时间


def test_find_cc_process_on_this_machine_matches_claude_pid():
    """真实进程链：本测试进程的祖先里有 CLAUDE_PID 时，必须找到它。"""
    if os.name != "nt" or not os.environ.get("CLAUDE_PID", "").isdigit():
        pytest.skip("不在 CC 里运行")
    got = load_hook().find_cc_process()
    assert got is not None and got["pid"] == int(os.environ["CLAUDE_PID"])
    assert got["created"] == winproc.process_created(got["pid"])


@pytest.fixture
def meta_env(tmp_path):
    events = []
    hub = RemoteHub()
    srv = ShionServer(lambda t, d, m=None: events.append((t, d, m)), lambda: "", port=0, hub=hub)
    srv.start()
    yield srv, events, tmp_path
    hub.resume()
    srv.stop()


def test_hook_sends_session_and_tool_id(meta_env):
    srv, events, tmp = meta_env
    stdin = json.dumps({"session_id": "s1", "tool_use_id": "t1", "tool_name": "Read"}).encode()
    run_hook("PreToolUse", srv.port, tmp, stdin=stdin)
    run_hook("PostToolUse", srv.port, tmp, stdin=stdin)
    (t1, _, m1), (t2, _, m2) = events
    assert (t1, m1["session"], m1["tool_id"]) == ("working", "s1", "t1")
    assert (t2, m2) == ("tool_done", {"session": "s1", "tool_id": "t1"})  # PostToolUse 不查进程


@pytest.mark.parametrize("name", ["PreToolUse", "PostToolUse"])
def test_interrupted_session_ends_turn_at_next_checkpoint(meta_env, name):
    srv, events, tmp = meta_env
    srv.hub.request_interrupt(["s1"])
    stdin = json.dumps({"session_id": "s1", "tool_use_id": "t1", "tool_name": "Bash"}).encode()
    r = run_hook(name, srv.port, tmp, stdin=stdin)
    out = json.loads(r.stdout.decode("utf-8"))
    assert out["continue"] is False and "claude" not in out["stopReason"].lower()
    assert not any(t in ("working", "tool_error") for t, _, _ in events)
    r2 = run_hook(name, srv.port, tmp, stdin=stdin)  # 只生效一次
    assert b'"continue": false' not in r2.stdout


def test_tool_failure_leaves_the_interrupt_for_the_next_checkpoint(meta_env):
    """被结束的工具会触发 PostToolUseFailure：CC 不理会它的 continue=false，所以标记要留给下一个检查点。"""
    srv, events, tmp = meta_env
    srv.hub.request_interrupt(["s1"])
    stdin = json.dumps({"session_id": "s1", "tool_use_id": "t1", "tool_name": "Bash", "error": "Exit code 1"}).encode()
    r = run_hook("PostToolUseFailure", srv.port, tmp, stdin=stdin)
    assert r.stdout == b"" and srv.hub.interrupt_pending("s1")
    r = run_hook("PreToolUse", srv.port, tmp, stdin=stdin)
    assert json.loads(r.stdout.decode("utf-8"))["continue"] is False


def test_other_session_is_not_interrupted(meta_env):
    srv, _, tmp = meta_env
    srv.hub.request_interrupt(["s1"])
    r = run_hook("PreToolUse", srv.port, tmp, stdin=json.dumps({"session_id": "s2"}).encode())
    assert r.stdout == b""


# ---------------------------------------------------------------- 结束工具进程（假进程表）
class FakeView:
    def __init__(self, table, created, images=None):
        self._table, self._created, self._images = table, created, images or {}
        self.killed = []

    def view(self):
        return interrupt.ProcessView(
            table=lambda: dict(self._table), created=lambda pid: self._created.get(pid),
            image=lambda pid: self._images.get(pid, ""), terminate=self._terminate)

    def _terminate(self, pid, created):
        self.killed.append(pid)
        self._table.pop(pid, None)
        return True


START = 1_800_000_000.0
CC = interrupt.CCProcess(100, ft(START - 3600), "claude.exe", "claude-desktop", [201])


def fake_world():
    table = {
        100: (1, "claude.exe"),
        150: (100, "node.exe"),  # MCP 服务器：会话开始时就有
        201: (100, "python.exe"),  # hook（报来的 pid）
        202: (100, "python.exe"),  # 另一个 hook（.venv 里的 python，按路径排除）
        300: (100, "cmd.exe"),  # 工具
        301: (300, "powershell.exe"),
        302: (301, "python.exe"),
        400: (999, "notepad.exe"),
    }
    created = {100: CC.created, 150: ft(START - 3500), 201: ft(START - 1), 202: ft(START + 2),
               300: ft(START + 0.2), 301: ft(START + 0.3), 302: ft(START + 0.4), 400: ft(START + 1)}
    images = {202: r"D:\desktop\work\claude pet\.venv\Scripts\python.exe"}
    return FakeView(table, created, images)


HOOK_IMAGES = (r"D:/desktop/work/claude pet/.venv/Scripts/python.exe",)


def test_only_tool_processes_started_after_the_tool_are_killed_deepest_first():
    w = fake_world()
    assert interrupt.interrupt(CC, [START], w.view(), HOOK_IMAGES) == [302, 301, 300]
    assert w.killed == [302, 301, 300]


def test_nothing_killed_when_no_tool_is_running():
    w = fake_world()
    assert interrupt.interrupt(CC, [], w.view(), HOOK_IMAGES) == []
    assert w.killed == []


def test_dead_or_reused_cc_pid_is_rejected():
    w = fake_world()
    w._created[100] = CC.created + 1  # PID 被复用
    assert interrupt.interrupt(CC, [START], w.view()) is None
    w = fake_world()
    del w._table[100]
    assert interrupt.interrupt(CC, [START], w.view()) is None
    assert w.killed == []


def test_reused_child_pid_older_than_its_parent_is_skipped():
    w = fake_world()
    w._created[302] = ft(START - 100)
    assert interrupt.interrupt(CC, [START], w.view(), HOOK_IMAGES) == [301, 300]


@pytest.mark.skipif(os.name != "nt", reason="Windows 进程")
def test_real_process_tree_is_terminated():
    """把本测试进程当作 CC：起一个 子进程 → 孙进程 的树，立即中断后两个都没了，本进程还在。"""
    me = os.getpid()
    proc = interrupt.CCProcess(me, winproc.process_created(me), winproc.process_table()[me][1].lower())
    start = time.time()
    code = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); time.sleep(60)"
    child = subprocess.Popen([sys.executable, "-c", code])
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        grand = [p for p, (pp, _) in winproc.process_table().items() if pp == child.pid]
        if grand:
            break
        time.sleep(0.05)
    assert grand
    killed = interrupt.interrupt(proc, [start], hook_images=())
    assert child.pid in killed and grand[0] in killed
    assert child.wait(5) is not None
    assert grand[0] not in winproc.process_table()


# ---------------------------------------------------------------- 控制器
@pytest.fixture
def pet2(env):  # noqa: F811
    world = fake_world()
    env.ctl.process_view = world.view()
    env.ctl.hook_images = HOOK_IMAGES
    env.world = world
    yield env
    env.ctl.hub.resume()


def work(env, session="s1", tool="t1", proc=None):
    env.ctl.handle_event("working", json.dumps({"tool": "bash", "target": ""}),
                         {"session": session, "tool_id": tool, "proc": proc or {
                             "pid": CC.pid, "created": CC.created, "name": CC.name, "entry": CC.entry,
                             "hooks": CC.hooks}})


def interrupt_action(env):
    menu = env.ctl.build_menu()
    remote = find_action(menu, "工作遥控").menu()
    return menu, find_action(remote, "立即中断")


def test_interrupt_is_disabled_when_idle(pet2):
    _, act = interrupt_action(pet2)
    assert not act.isEnabled()
    pet2.ctl.interrupt_work()  # 硬点也什么都不发
    assert pet2.world.killed == [] and not pet2.ctl.hub.interrupt_pending("s1")


def test_interrupt_kills_tool_flags_session_and_goes_idle(pet2):
    pet2.now = T0
    work(pet2)
    # 工具开始时间 = 收到 PreToolUse 的时刻；假进程表按这个时间造
    start = pet2.ctl._tool_wall["s1"]["t1"]
    pet2.world._created.update({300: ft(start + 0.2), 301: ft(start + 0.3), 302: ft(start + 0.4),
                                150: ft(start - 3500), 201: ft(start - 1), 202: ft(start + 2)})
    _, act = interrupt_action(pet2)
    assert act.isEnabled()
    act.trigger()
    assert pet2.world.killed == [302, 301, 300]
    assert pet2.ctl.hub.interrupt_pending("s1")
    assert pet2.said[-1] == "命令停掉了，等它说完这句就停～"
    assert pet2.win.sprite_name == "stop"
    assert not pet2.state.is_working(pet2.now)
    _, act = interrupt_action(pet2)
    assert not act.isEnabled()  # 发过一次就是空闲，不会再发
    pet2.ctl.interrupt_work()
    assert pet2.world.killed == [302, 301, 300]


def test_interrupt_without_process_falls_back_to_stop(pet2):
    pet2.ctl.handle_event("working", None, {"session": "s1", "tool_id": "t1"})  # hook 没找到 CC 进程
    pet2.ctl.interrupt_work()
    assert pet2.said[-1] == NO_PROCESS
    assert pet2.ctl.hub.is_paused and pet2.state.paused
    assert not pet2.ctl.hub.interrupt_pending("s1")


@pytest.mark.parametrize("lang", ["zh", "en", "ja"])
@pytest.mark.parametrize("has_command", [True, False])
def test_interrupt_two_stage_speech_uses_actual_kills_and_waits_for_own_checkpoint(
        pet2, lang, has_command):
    e = pet2
    e.ctl.set_language(lang)
    work(e)
    start = e.ctl._tool_wall["s1"]["t1"]
    e.world._created.update({300: ft(start + 0.2), 301: ft(start + 0.3), 302: ft(start + 0.4),
                             150: ft(start - 3500), 201: ft(start - 1), 202: ft(start + 2)})
    if not has_command:
        e.ctl.handle_event("tool_done", None, {"session": "s1", "tool_id": "t1"})
    e.ctl.interrupt_work()
    key = "interrupt_command_stopped" if has_command else "interrupt_waiting"
    assert e.said[-1] == e.ctl.lines.ui(key)
    assert e.win.sprite_name == "stop"
    assert bool(e.world.killed) == has_command
    e.said.clear()
    e.ctl.handle_event("work_stopped", None, {"session": "other"})
    assert e.said == []
    e.ctl.handle_event("work_stopped", None, {"session": "s1"})
    assert e.said == [e.ctl.lines.ui("interrupted")]
    assert e.win.sprite_name == "stop"
    e.ctl.handle_event("work_stopped", None, {"session": "s1"})
    e.ctl.handle_event("stop", None, {"session": "s1"})
    assert e.said == [e.ctl.lines.ui("interrupted")]
    assert e.data.stats["claude_tasks"] == 0


def test_failed_termination_does_not_claim_command_stopped(pet2):
    work(pet2)
    pet2.world._terminate = lambda *args: False
    pet2.ctl.process_view = pet2.world.view()
    pet2.ctl.interrupt_work()
    assert pet2.said[-1] == "等它说完这句就停～"


@pytest.mark.parametrize("muted_at_click,muted_at_end", [(True, True), (True, False), (False, True)])
def test_each_interrupt_stage_obeys_current_mute_setting(pet2, muted_at_click, muted_at_end):
    work(pet2)
    pet2.said.clear()
    pet2.data.bubble_muted = muted_at_click
    pet2.ctl.interrupt_work()
    assert bool(pet2.said) != muted_at_click
    assert pet2.win.sprite_name == "stop"
    pet2.said.clear()
    pet2.data.bubble_muted = muted_at_end
    pet2.ctl.handle_event("work_stopped", None, {"session": "s1"})
    assert pet2.said == ([] if muted_at_end else [INTERRUPTED])
    assert pet2.win.sprite_name == "stop"


@pytest.mark.parametrize("event", ["prompt", "stop", "pause_timeout"])
def test_new_turn_or_other_end_discards_pending_interrupt_speech(pet2, event):
    work(pet2)
    pet2.ctl.interrupt_work()
    pet2.ctl.handle_event(event, None, {"session": "s1"})
    pet2.said.clear()
    pet2.ctl.handle_event("work_stopped", None, {"session": "s1"})
    assert INTERRUPTED not in pet2.said


def test_interrupt_with_dead_process_falls_back_to_stop(pet2):
    work(pet2)
    del pet2.world._table[CC.pid]
    pet2.ctl.interrupt_work()
    assert pet2.said[-1] == NO_PROCESS and pet2.state.paused


def test_interrupt_while_stopped_releases_waiting_hook_with_stop(pet2):
    work(pet2)
    pet2.ctl.stop_work()
    results = []
    t = threading.Thread(target=lambda: results.append(pet2.ctl.hub.wait_gate(5, "s1")), daemon=True)
    t.start()
    deadline = time.monotonic() + 3
    while pet2.ctl.hub._holding < 1 and time.monotonic() < deadline:
        time.sleep(0.01)
    pet2.ctl.interrupt_work()
    t.join(5)
    assert results and results[0][1] is True
    assert not pet2.state.paused and not pet2.ctl.hub.is_paused


def test_interrupt_applies_to_every_working_session(pet2):
    work(pet2, "a", "t1")
    work(pet2, "b", "t2")
    pet2.ctl.interrupt_work()
    assert pet2.ctl.hub.interrupt_pending("a") and pet2.ctl.hub.interrupt_pending("b")
    assert pet2.state.working_sessions(pet2.now) == []


def test_pause_timeout_ends_that_session(pet2):
    work(pet2, "a", "t1")
    work(pet2, "b", "t2")
    pet2.ctl.stop_work()
    pet2.ctl.handle_event("pause_timeout", None, {"session": "a"})
    assert pet2.state.working_sessions(pet2.now) == ["b"] and not pet2.state.paused


def test_hook_timeout_reports_its_session(meta_env):
    srv, events, tmp = meta_env
    srv.hub.pause()
    code = (
        "import sys, importlib.util;"
        f"spec = importlib.util.spec_from_file_location('h', {str(HOOK)!r});"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m);"
        "m.pause_limit = lambda: 1; sys.argv = ['x', 'PostToolUse']; m.main()"
    )
    r = subprocess.run([sys.executable, "-c", code], input=json.dumps({"session_id": "s1"}).encode(),
                       capture_output=True, timeout=20,
                       env={**os.environ, "SHION_PORT": str(srv.port), "SHION_DATA_DIR": str(tmp)})
    assert json.loads(r.stdout)["continue"] is False
    assert ("pause_timeout", None, {"session": "s1"}) in events


def test_work_stopped_event_ends_only_that_session(pet2):
    work(pet2, "a", "t1")
    work(pet2, "b", "t2")
    pet2.ctl.handle_event("work_stopped", None, {"session": "a"})
    assert pet2.state.working_sessions(pet2.now) == ["b"]
    assert pet2.win.sprite_name == "working"


def test_two_sessions_stop_says_done_then_back_to_working(pet2):
    work(pet2, "a", "t1")
    work(pet2, "b", "t2")
    pet2.said.clear()
    pet2.ctl.handle_event("stop", None, {"session": "a"})
    assert pet2.win.sprite_name == "done"
    assert any(t in pet2.ctl.lines._lines["claude_done"] for t in pet2.said)
    pet2.advance(4)
    assert pet2.win.sprite_name == "working"
    pet2.ctl.handle_event("stop", None, {"session": "b"})
    pet2.advance(4)
    assert pet2.win.sprite_name != "working"


def test_long_tool_stays_working_in_controller(pet2):
    work(pet2)
    for _ in range(20):
        pet2.advance(60)  # 20 分钟没有新事件，但工具还在跑
    assert pet2.win.sprite_name == "working"
    pet2.ctl.handle_event("tool_done", None, {"session": "s1", "tool_id": "t1"})
    pet2.advance(301)
    assert pet2.win.sprite_name != "working"


def test_tool_failure_after_interrupt_is_not_reported_as_error(pet2):
    work(pet2)
    pet2.ctl.interrupt_work()
    pet2.said.clear()
    pet2.ctl.handle_event("tool_error", "Bash", {"session": "s1", "tool_id": "t1"})
    assert pet2.said == [] and pet2.win.sprite_name != "dizzy"
    pet2.ctl.handle_event("prompt", None, {"session": "s1"})  # 重新开始后，出错照常说
    pet2.ctl.handle_event("tool_error", "Bash", {"session": "s1", "tool_id": "t2"})
    assert pet2.win.sprite_name == "dizzy"



# ---------------------------------------------------------------- 诗音结束的这一轮：紧接着的 Stop 不算完成
def _done_lines(env):
    return [t for t in env.said if t in env.ctl.lines._lines["claude_done"]]


def _assert_stop_not_counted(env, session="s1"):
    assert env.state.save.stats["claude_tasks"] == 0
    assert env.win.sprite_name != "done"
    assert _done_lines(env) == []
    assert env.state._stopped_at is None  # 不会再催“结果还在等你看呢”
    assert [e.kind for e in env.ctl.activity.recent(20)].count("stop") == 0
    assert env.ctl._ended is not None and env.ctl._ended[0] == session  # 仍提供“继续”


def test_stop_right_after_interrupt_is_not_a_finished_task(pet2):
    work(pet2)
    pet2.ctl.interrupt_work()
    pet2.said.clear()
    pet2.ctl.handle_event("stop", None, {"session": "s1"})  # 中断后 CC 写完一句话照常 Stop
    _assert_stop_not_counted(pet2)
    for _ in range(12):
        pet2.advance(60)  # 过了催促时间也不催
    assert not any(t in pet2.ctl.lines._lines["nudge"] for t in pet2.said)


@pytest.mark.parametrize("etype", ["work_stopped", "pause_timeout"])
def test_stop_after_shion_ended_the_turn_is_not_counted(pet2, etype):
    work(pet2)
    if etype == "pause_timeout":
        pet2.ctl.stop_work()
    pet2.ctl.handle_event(etype, None, {"session": "s1"})
    pet2.said.clear()
    pet2.ctl.handle_event("stop", None, {"session": "s1"})
    _assert_stop_not_counted(pet2)


def test_only_the_next_stop_is_swallowed(pet2):
    work(pet2)
    pet2.ctl.interrupt_work()
    pet2.ctl.handle_event("stop", None, {"session": "s1"})
    pet2.ctl.handle_event("stop", None, {"session": "s1"})  # 第二次 Stop 照常算
    assert pet2.state.save.stats["claude_tasks"] == 1


def test_new_prompt_clears_the_mark(pet2):
    work(pet2)
    pet2.ctl.handle_event("work_stopped", None, {"session": "s1"})  # CC 没发 Stop
    pet2.ctl.handle_event("prompt", None, {"session": "s1"})  # 用户在 CC 里接着说
    work(pet2)
    pet2.said.clear()
    pet2.ctl.handle_event("stop", None, {"session": "s1"})
    assert pet2.state.save.stats["claude_tasks"] == 1 and _done_lines(pet2)


def test_other_sessions_stop_still_counts(pet2):
    work(pet2, "a", "t1")
    pet2.ctl.handle_event("work_stopped", None, {"session": "a"})
    work(pet2, "b", "t2")
    pet2.ctl.handle_event("stop", None, {"session": "b"})
    assert pet2.state.save.stats["claude_tasks"] == 1


# ---------------------------------------------------------------- idle_prompt：CC 在等输入，清掉工作中
def test_idle_prompt_clears_tool_in_flight(pet2):
    work(pet2, "a", "t1")  # 例如 AskUserQuestion 上按 Esc：没有 PostToolUse / Stop
    work(pet2, "b", "t2")
    pet2.ctl.handle_event("notification", "idle_prompt", {"session": "a"})
    assert pet2.state.working_sessions(pet2.now) == ["b"]
    assert "a" not in pet2.ctl._tool_wall and "b" in pet2.ctl._tool_wall
    pet2.ctl.handle_event("notification", "idle_prompt", {"session": "b"})
    assert not pet2.state.is_working(pet2.now)
    pet2.advance(4)
    assert pet2.win.sprite_name != "working"


def test_other_notification_types_keep_working(pet2):
    work(pet2)
    for kind in ("permission_prompt", None):
        pet2.ctl.handle_event("notification", kind, {"session": "s1"})
    assert pet2.state.working_sessions(pet2.now) == ["s1"]
