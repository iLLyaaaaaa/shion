"""临时关闭和 Claude Code 的联动：诗音表现得像没开。

安全不变量：关闭时任何 HTTP 请求、任何字段组合都不能让 hook 输出 allow；切换瞬间正在长轮询的授权只能得到无决定；
PreToolUse / PostToolUse 不输出 deny 或 continue:false。
"""
import json
import threading
import time

import pytest

from shion import state as S
from shion.remote import DISABLED, PermissionQueue, RemoteHub
from shion.server import ShionServer
from tests.test_controller import Env, env, qapp  # noqa: F401
from tests.test_hook import load_hook, run_hook
from tests.test_permission import FORGERIES, perm_input, post, start_hook, wait_pending

ROUTES = ("/event", "/feedback/take", "/pause/wait", "/permission/open", "/permission/wait",
          "/permission/withdraw", "/permission/settle")


@pytest.fixture
def linked(tmp_path):
    """真实 HTTP 服务；记录事件和取反馈的调用，反馈队列只有被取走时才清空。"""
    events, taken, queue = [], [], ["[诗音] 反馈"]

    def take():
        taken.append(True)
        text = "\n".join(queue)
        queue.clear()
        return text

    hub = RemoteHub()
    srv = ShionServer(lambda t, d, m=None: events.append((t, d, m)), take, port=0, hub=hub)
    srv.start()
    yield srv, hub, events, taken, queue, tmp_path
    srv.stop()


def no_decision(out: bytes):
    text = out.decode("utf-8")
    assert '"allow"' not in text and '"deny"' not in text and '"continue": false' not in text, text
    return text


# ---------------------------------------------------------------- 共享状态
def test_queue_close_withdraws_everything_and_refuses_new_work():
    q = PermissionQueue()
    pending, decided = q.open("Bash", "a"), q.open("Bash", "b")
    assert q.decide(decided, True)  # 用户已经点了同意，但 hook 还没来取
    q.close()
    assert q.pending() == [] and q.closed
    assert q.wait(pending, 0) == "gone" and q.wait(decided, 0) == "gone"
    assert q.open("Bash", "c") == DISABLED and q.pending() == []
    assert not q.decide(decided, True)
    q.reopen()
    assert q.wait(decided, 0) == "gone"  # 重新开启不恢复关闭前的任何请求
    rid = q.open("Bash", "d")
    assert rid != DISABLED and q.wait(rid, 0) == "pending"


def test_closed_queue_never_decides_even_if_an_item_slips_in():
    from shion.remote import PermissionRequest
    q = PermissionQueue()
    q.close()
    q._items["x"] = PermissionRequest("x", "Bash", "d", 0, 0, status="allow")  # 假设有已决定的条目漏进来
    assert q.wait("x", 0) == "gone"


def test_hub_disable_releases_gate_without_stop_and_clears_flags():
    hub = RemoteHub()
    hub.pause()
    hub.request_interrupt(["s"])
    hub.set_link_enabled(False)
    assert not hub.is_paused and not hub.interrupt_pending("s")
    hub.pause()  # 即使界面层出错又设了暂停/中断，关闭时检查点也不停、不中断
    hub.request_interrupt(["s"])
    assert hub.wait_gate(5, "s") == (False, False)
    hub.set_link_enabled(True)
    assert hub.link_enabled and not hub.permissions.closed


def test_gate_waiting_at_toggle_moment_is_released_without_stop():
    hub = RemoteHub()
    hub.pause()
    result = []
    t = threading.Thread(target=lambda: result.append(hub.wait_gate(10, "s")))
    t.start()
    time.sleep(0.2)
    t0 = time.monotonic()
    hub.set_link_enabled(False)
    t.join(5)
    assert result == [(False, False)] and time.monotonic() - t0 < 2


# ---------------------------------------------------------------- HTTP
@pytest.mark.parametrize("extra", FORGERIES + [{}])
def test_disabled_routes_never_produce_allow_with_any_fields(linked, extra):
    srv, hub, events, taken, queue, _ = linked
    rid = post(srv, "/permission/open", {"tool": "Bash", "detail": "x"})[1]["id"]
    hub.permissions.decide(rid, True)  # 有一个没被取走的同意
    hub.set_link_enabled(False)
    bodies = []
    for etype in ("permission_allow", "allow", "react", "prompt", "stop", "working", "plan_ready", "pause_timeout"):
        bodies.append(post(srv, "/event", {"type": etype, "detail": json.dumps(extra), "session": "s", **extra}))
    for rid_value in (rid, "x" * 32, "", "disabled"):
        bodies.append(post(srv, "/permission/wait", {"id": rid_value, "wait": 0, **extra}))
        bodies.append(post(srv, "/permission/withdraw", {"id": rid_value, **extra}))
    bodies.append(post(srv, "/permission/open", {"tool": "Bash", "detail": "x", "session": "s", "key": "ab", **extra}))
    bodies.append(post(srv, "/permission/settle", {"session": "s", **extra}))
    bodies.append(post(srv, "/pause/wait", {"wait": 0, "session": "s", **extra}))
    bodies.append(post(srv, "/feedback/take", dict(extra)))
    for path in ("/permission/allow", "/permission/decide", "/permission"):
        bodies.append(post(srv, path, {"id": rid, **extra}))
    dump = json.dumps(bodies)
    assert '"allow"' not in dump and '"deny"' not in dump
    assert all("id" not in b for s, b in bodies if "disabled" in b)
    assert events == [] and taken == [] and queue == ["[诗音] 反馈"]
    assert hub.permissions.pending() == [] and not hub.is_paused


def test_disabled_route_responses(linked):
    srv, hub, events, taken, queue, _ = linked
    hub.set_link_enabled(False)
    assert post(srv, "/event", {"type": "prompt", "session": "s"}) == (200, {"ok": True, "ignored": True})
    assert post(srv, "/event", {"type": ""})[0] == 400  # 校验照旧
    assert post(srv, "/permission/open", {"tool": "Bash", "detail": "x"}) == (200, {"disabled": True})
    assert post(srv, "/permission/wait", {"id": "a", "wait": 5}) == (200, {"id": "a", "status": "gone"})
    t0 = time.monotonic()
    assert post(srv, "/pause/wait", {"wait": 20, "session": "s"}) == (200, {"paused": False, "stop": False})
    assert time.monotonic() - t0 < 2
    assert post(srv, "/feedback/take", {}) == (200, {"text": ""})
    assert events == [] and taken == [] and queue == ["[诗音] 反馈"]
    hub.set_link_enabled(True)  # 重新开启：反馈还在，照常取走
    assert post(srv, "/feedback/take", {}) == (200, {"text": "[诗音] 反馈"})


def test_long_poll_at_toggle_moment_only_gets_gone(linked):
    srv, hub, *_ = linked
    rid = post(srv, "/permission/open", {"tool": "Bash", "detail": "x"})[1]["id"]
    result = []
    t = threading.Thread(target=lambda: result.append(post(srv, "/permission/wait", {"id": rid, "wait": 20})))
    t.start()
    time.sleep(0.3)
    hub.set_link_enabled(False)
    t.join(5)
    assert result == [(200, {"id": rid, "status": "gone"})]


def test_pause_wait_holding_at_toggle_moment_is_released_without_work_stopped(linked):
    srv, hub, events, *_ = linked
    hub.pause()
    result = []
    t = threading.Thread(target=lambda: result.append(post(srv, "/pause/wait", {"wait": 20, "session": "s"})))
    t.start()
    time.sleep(0.3)
    hub.set_link_enabled(False)
    t.join(5)
    assert result == [(200, {"paused": False, "stop": False})]
    assert not any(e[0] == "work_stopped" for e in events)


# ---------------------------------------------------------------- hook 进程
def test_hook_permission_request_gives_no_decision_when_disabled(linked):
    srv, hub, events, _, _, tmp = linked
    hub.set_link_enabled(False)
    t0 = time.monotonic()
    r = run_hook("PermissionRequest", srv.port, tmp, perm_input("Bash", command="rm -rf build"))
    assert r.returncode == 0 and r.stdout == b"" and r.stderr == b""
    assert time.monotonic() - t0 < 10 and hub.permissions.pending() == []


def test_hook_long_polling_at_toggle_moment_gives_no_decision(linked):
    srv, hub, _, _, _, tmp = linked
    proc = start_hook(srv, tmp, perm_input("Bash", command="npm test"))
    wait_pending(hub)
    hub.set_link_enabled(False)
    out, err = proc.communicate(timeout=15)
    assert proc.returncode == 0 and out == b"" and err == b""


def test_hook_decided_but_uncollected_allow_is_dropped_by_toggle(monkeypatch):
    """用户点了同意、hook 还没来取，这时关闭：hook 下一次轮询只能拿到 gone，不给决定。"""
    hook = load_hook()
    hub = RemoteHub()
    calls = []

    def fake_request(path, payload=None, timeout=None):
        calls.append(path)
        if path == "/permission/open":
            rid = hub.permissions.open("Bash", "x")
            hub.permissions.decide(rid, True)
            hub.set_link_enabled(False)
            return {"id": rid}
        if path == "/permission/wait":
            return {"id": payload["id"], "status": hub.permissions.wait(payload["id"], 0)}
        return {"ok": True}
    monkeypatch.setattr(hook, "request", fake_request)
    assert hook.permission_decision({"tool_name": "Bash", "tool_input": {"command": "x"}}, 5) is None


@pytest.mark.parametrize("name", ["PreToolUse", "PostToolUse"])
def test_checkpoints_never_deny_or_stop_when_disabled(linked, name):
    srv, hub, events, taken, queue, tmp = linked
    hub.pause()
    hub.request_interrupt(["sess"])
    hub.set_link_enabled(False)
    hub.pause()  # 关闭后再被设上的暂停/中断也不能生效
    hub.request_interrupt(["sess"])
    stdin = json.dumps({"session_id": "sess", "tool_name": "Bash", "tool_input": {"command": "ls"},
                        "tool_use_id": "t1"}).encode()
    r = run_hook(name, srv.port, tmp, stdin)
    assert r.returncode == 0 and r.stderr == b""
    assert no_decision(r.stdout) == ""  # 反馈也不注入：队列保留
    assert events == [] and taken == [] and queue == ["[诗音] 反馈"]


@pytest.mark.parametrize("name", ["PreToolUse", "PostToolUse"])
def test_hook_held_at_checkpoint_is_released_by_toggle_without_stop(linked, name):
    srv, hub, events, _, _, tmp = linked
    hub.pause()
    stdin = json.dumps({"session_id": "sess", "tool_name": "Bash", "tool_input": {"command": "ls"}}).encode()
    proc = start_hook(srv, tmp, stdin, name=name)
    deadline = time.monotonic() + 10
    while not hub.is_holding and time.monotonic() < deadline:
        time.sleep(0.05)
    assert hub.is_holding
    hub.set_link_enabled(False)
    out, err = proc.communicate(timeout=15)
    assert proc.returncode == 0 and err == b"" and no_decision(out) == ""
    assert not any(e[0] in ("work_stopped", "pause_timeout") for e in events)


def test_user_prompt_submit_does_not_take_feedback_when_disabled(linked):
    srv, hub, events, taken, queue, tmp = linked
    hub.set_link_enabled(False)
    r = run_hook("UserPromptSubmit", srv.port, tmp, json.dumps({"session_id": "s", "prompt": "hi"}).encode())
    assert r.returncode == 0 and r.stdout == b"" and taken == [] and queue == ["[诗音] 反馈"]


# ---------------------------------------------------------------- 界面与存档
def test_toggle_off_resets_everything_to_idle_and_persists(env):
    ctl, state = env.ctl, env.state
    ctl.handle_event("prompt", None, {"session": "s1"})
    ctl.handle_event("working", "bash", {"session": "s1", "tool_id": "t1"})
    ctl.stop_work()
    rid = ctl.hub.permissions.open("Bash", "rm", session="s1")
    env.advance(0.1)
    assert state.paused and ctl.hub.permissions.pending() and ctl._perm_panel.isVisible()
    said = len(env.said)
    ctl.toggle_claude_link()
    assert not ctl.hub.link_enabled and not state.paused and not ctl.hub.is_paused
    assert ctl.hub.permissions.pending() == [] and not ctl._perm_panel.isVisible()
    assert ctl.hub.permissions.wait(rid, 0) == "gone"
    assert not state.is_working(env.now) and state.working_sessions(env.now) == []
    assert ctl._procs == {} and ctl._tool_wall == {} and ctl._ended is None
    assert env.win.sprite_name not in ("working", "stop")
    assert len(env.said) == said  # 关闭时不说话
    assert S.load(env.path).claude_link_enabled is False
    assert ctl.claude_activity() == "off"


def test_events_while_disabled_change_nothing_and_are_not_replayed(env):
    ctl, state = env.ctl, env.state
    ctl.toggle_claude_link()
    before = (env.win.sprite_name, len(env.said), state.save.stats["claude_tasks"])
    for etype, detail in (("prompt", None), ("working", "bash"), ("stop", None), ("plan_ready", None),
                          ("react", "happy"), ("pause_timeout", None), ("work_stopped", None)):
        ctl.handle_event(etype, detail, {"session": "s1"})
    env.advance(1)
    assert (env.win.sprite_name, len(env.said), state.save.stats["claude_tasks"]) == before
    assert not state.is_working(env.now)
    ctl.toggle_claude_link()  # 重新开启：不补播，从空闲开始
    env.advance(1)
    assert ctl.hub.link_enabled and not state.is_working(env.now) and ctl.claude_activity() == "idle"
    assert len(env.said) == before[1] and S.load(env.path).claude_link_enabled is True


def test_remote_controls_are_inert_while_disabled_but_feedback_queue_is_kept(env):
    ctl, state = env.ctl, env.state
    state.save.feedback_queue = [{"kind": "bad", "text": "之前的反馈"}]
    ctl.toggle_claude_link()
    ctl.stop_work()
    assert not state.paused and not ctl.hub.is_paused
    assert not ctl.can_interrupt()
    ctl.interrupt_work()
    ctl.continue_ended()
    assert state.save.feedback_queue == [{"kind": "bad", "text": "之前的反馈"}]


def test_saved_disabled_flag_applies_before_server_starts(qapp, tmp_path):
    path = tmp_path / "state.json"
    data = S.SaveData()
    data.claude_link_enabled = False
    S.save(path, data)
    e = Env(tmp_path)
    try:
        assert not e.ctl.hub.link_enabled and e.ctl.hub.permissions.closed
    finally:
        e.close()


def test_old_save_without_field_defaults_to_enabled(tmp_path):
    assert S.SaveData.from_dict({"schema_version": 5}).claude_link_enabled is True
    assert S.SaveData.from_dict({"claude_link_enabled": "no"}).claude_link_enabled is True
    data = S.SaveData()
    data.claude_link_enabled = False
    assert S.SaveData.from_dict(data.to_dict()).claude_link_enabled is False
