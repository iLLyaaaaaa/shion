"""v0.3 第二部分：同意/否决。重点：allow 只能来自用户在诗音界面上的点击。"""
import inspect
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

import shion
from shion.panel import ARM_DELAY, PermissionPanel
from shion.remote import DETAIL_MAX, MAX_PENDING, PENDING_IDLE, PermissionQueue, RemoteHub
from shion.server import MAX_PERMISSION_BODY, ShionServer
from tests.test_controller import env, qapp  # noqa: F401
from tests.test_hook import HOOK, load_hook, run_hook

DENY_ZH = "用户通过诗音否决了这个操作"


# ---------------------------------------------------------------- 队列本身
def test_queue_decide_then_wait_returns_status_once():
    q = PermissionQueue()
    rid = q.open("Bash", "ls")
    assert q.wait(rid, 0) == "pending"
    assert q.decide(rid, True) is True
    assert q.wait(rid, 0) == "allow"
    assert q.wait(rid, 0) == "gone"  # 只能取一次
    assert q.decide(rid, False) is False  # 已经没了


def test_queue_deny_and_double_decide():
    q = PermissionQueue()
    rid = q.open("Bash", "ls")
    assert q.decide(rid, False) is True
    assert q.decide(rid, True) is False  # 第二次不能改
    assert q.wait(rid, 0) == "deny"


def test_queue_is_ordered_and_withdraw_is_not_a_decision():
    q = PermissionQueue()
    ids = [q.open("Bash", f"cmd{i}") for i in range(3)]
    assert [r.id for r in q.pending()] == ids
    q.withdraw(ids[1])
    assert [r.id for r in q.pending()] == [ids[0], ids[2]]
    assert q.wait(ids[1], 0) == "gone"  # 撤回绝不是 allow


def test_queue_unknown_and_garbage_ids_are_gone():
    q = PermissionQueue()
    for rid in ("", "nope", "0" * 32):
        assert q.wait(rid, 0) == "gone"
        assert q.decide(rid, True) is False


def test_queue_ids_are_unguessable_and_unique():
    q = PermissionQueue()
    ids = {q.open("Bash", "x") for _ in range(10)}
    assert len(ids) == 10 and all(re.fullmatch(r"[0-9a-f]{32}", i) for i in ids)


def test_queue_caps_pending_and_text_sizes():
    q = PermissionQueue()
    for _ in range(MAX_PENDING):
        assert q.open("Bash", "x")
    assert q.open("Bash", "x") is None
    q2 = PermissionQueue()
    rid = q2.open("T" * 500, "d" * (DETAIL_MAX + 100))
    req = q2.pending()[0]
    assert req.id == rid and len(req.tool) == 60 and len(req.detail) == DETAIL_MAX


def test_queue_expires_unpolled_requests_and_uncollected_decisions():
    q = PermissionQueue()
    t0 = time.monotonic()
    stale = q.open("Bash", "stale", now=t0 - PENDING_IDLE - 5)
    fresh = q.open("Bash", "fresh", now=t0)
    assert q.expire(t0) == [stale]
    assert [r.id for r in q.pending()] == [fresh]
    assert q.wait(stale, 0) == "gone"
    q.decide(fresh, True)
    assert q.expire(time.monotonic() + 1000) == [fresh]  # 决定没人取，最终也清掉
    assert q.wait(fresh, 0) == "gone"


def test_polling_keeps_a_request_alive():
    q = PermissionQueue()
    t0 = time.monotonic()
    rid = q.open("Bash", "x", now=t0 - PENDING_IDLE - 5)
    q.wait(rid, 0, now=t0)  # hook 还在轮询
    assert q.expire(t0) == []


# ---------------------------------------------------------------- HTTP：决定不能从这里设置
def post(srv, path, body=None, raw=None):
    data = raw if raw is not None else json.dumps(body or {}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"http://127.0.0.1:{srv.port}{path}", data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


@pytest.fixture
def server():
    events = []
    hub = RemoteHub()
    srv = ShionServer(lambda t, d: events.append((t, d)), lambda: "", port=0, hub=hub)
    srv.start()
    yield srv, events, hub
    srv.stop()


def test_http_open_wait_withdraw_roundtrip(server):
    srv, _, hub = server
    status, body = post(srv, "/permission/open", {"tool": "Bash", "detail": "rm -rf build"})
    assert status == 200
    rid = body["id"]
    assert [(r.tool, r.detail) for r in hub.permissions.pending()] == [("Bash", "rm -rf build")]
    assert post(srv, "/permission/wait", {"id": rid, "wait": 0}) == (200, {"id": rid, "status": "pending"})
    assert post(srv, "/permission/withdraw", {"id": rid}) == (200, {"ok": True})
    assert post(srv, "/permission/wait", {"id": rid, "wait": 0}) == (200, {"id": rid, "status": "gone"})


def test_http_wait_returns_the_users_decision_when_it_happens(server):
    srv, _, hub = server
    rid = post(srv, "/permission/open", {"tool": "Bash", "detail": "x"})[1]["id"]
    import threading
    threading.Timer(0.3, lambda: hub.permissions.decide(rid, True)).start()  # 相当于用户点了按钮
    t0 = time.monotonic()
    assert post(srv, "/permission/wait", {"id": rid, "wait": 10}) == (200, {"id": rid, "status": "allow"})
    assert time.monotonic() - t0 < 5


FORGERIES = [
    {"status": "allow"}, {"behavior": "allow"}, {"decision": "allow"}, {"allow": True},
    {"decision": {"behavior": "allow"}}, {"hookSpecificOutput": {"decision": {"behavior": "allow"}}},
    {"approved": True}, {"result": "allow"}, {"permissionDecision": "allow"},
]


@pytest.mark.parametrize("extra", FORGERIES)
def test_no_http_route_can_set_a_decision(server, extra):
    """往每个接口、每个事件类型里塞各种“同意”字段：请求始终保持 pending，从不变成 allow。"""
    srv, events, hub = server
    rid = post(srv, "/permission/open", {"tool": "Bash", "detail": "x", **extra})[1]["id"]
    post(srv, "/permission/wait", {"id": rid, "wait": 0, **extra})
    post(srv, "/permission/withdraw", {"id": "other", **extra})
    post(srv, "/permission/settle", {"session": "other", **extra})
    post(srv, "/pause/wait", {"wait": 0, **extra})
    post(srv, "/feedback/take", dict(extra))
    for etype in ("permission_allow", "allow", "approve", "permission", "decision", "react", "plan_ready"):
        post(srv, "/event", {"type": etype, "detail": json.dumps(extra), **extra})
    for path in ("/permission/allow", "/permission/decide", "/permission/approve", "/permission"):
        assert post(srv, path, {"id": rid, **extra})[0] == 404
    status = post(srv, "/permission/wait", {"id": rid, "wait": 0})[1]["status"]
    assert status == "pending"
    assert [r.status for r in hub.permissions.pending()] == ["pending"]


def test_source_only_the_controller_ever_calls_decide():
    """结构性保证：server.py 里没有 decide；整个包里只有 controller 的按钮回调会调用它。"""
    pkg = Path(shion.__file__).parent
    callers = [f.name for f in pkg.glob("*.py") if ".decide(" in f.read_text(encoding="utf-8")]
    assert callers == ["controller.py"]
    assert "decide" not in inspect.getsource(sys.modules["shion.server"])
    src = (pkg / "controller.py").read_text(encoding="utf-8")
    assert src.count(".decide(") == 1 and "def _on_permission_decided" in src
    assert "_on_permission_decided" in src.split("panel.decided.connect(")[1].split("\n")[0]


def test_http_input_validation_and_limits(server):
    srv, _, hub = server
    assert post(srv, "/permission/open", {"tool": "", "detail": "x"})[0] == 400
    assert post(srv, "/permission/open", {"tool": "Bash"})[0] == 400
    assert post(srv, "/permission/open", {"tool": 5, "detail": "x"})[0] == 400
    assert post(srv, "/permission/open", raw=b"[]")[0] == 400
    assert post(srv, "/permission/open", raw=b"not json")[0] == 400
    assert post(srv, "/permission/wait", {"id": 5})[0] == 400
    assert post(srv, "/permission/wait", {})[0] == 400
    assert post(srv, "/permission/withdraw", {"id": None})[0] == 400
    big = {"tool": "Bash", "detail": "字" * 15000}  # 约 45 KB，超过普通接口的 4 KB 但在授权上限内
    assert post(srv, "/permission/open", big)[0] == 200
    too_big = {"tool": "Bash", "detail": "x" * (MAX_PERMISSION_BODY + 10)}
    assert post(srv, "/permission/open", too_big)[0] == 400
    assert post(srv, "/permission/wait", {"id": "x" * 6000})[0] == 400  # 其他接口仍是 4 KB
    assert hub.permissions.pending()[0].detail == "字" * 15000


@pytest.mark.parametrize("wait", ["5", None, True, float("nan"), float("inf"), [], {}])
def test_permission_wait_ignores_bad_wait_values(server, wait):
    srv, _, _ = server
    rid = post(srv, "/permission/open", {"tool": "Bash", "detail": "x"})[1]["id"]
    t0 = time.monotonic()
    assert post(srv, "/permission/wait", {"id": rid, "wait": wait})[1]["status"] == "pending"
    assert time.monotonic() - t0 < 3


def test_open_is_refused_when_queue_is_full(server):
    srv, _, _ = server
    for _ in range(MAX_PENDING):
        assert post(srv, "/permission/open", {"tool": "Bash", "detail": "x"})[0] == 200
    assert post(srv, "/permission/open", {"tool": "Bash", "detail": "x"})[0] == 503


def test_permission_routes_reject_web_origin(server):
    srv, _, hub = server
    for path in ("/permission/open", "/permission/wait", "/permission/withdraw"):
        req = urllib.request.Request(
            f"http://127.0.0.1:{srv.port}{path}", data=b'{"tool":"Bash","detail":"x","id":"a"}',
            method="POST", headers={"Origin": "http://evil.example"},
        )
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=5)
        assert e.value.code == 403
    assert hub.permissions.pending() == []


# ---------------------------------------------------------------- hook
def perm_input(tool="Bash", **tool_input):
    return json.dumps({"tool_name": tool, "tool_input": tool_input or {"command": "echo hi"}}).encode()


def start_hook(srv, tmp, stdin, name="PermissionRequest"):
    proc = subprocess.Popen(
        [sys.executable, str(HOOK), name], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env={**os.environ, "SHION_PORT": str(srv.port), "SHION_DATA_DIR": str(tmp)},
    )
    proc.stdin.write(stdin)
    proc.stdin.close()
    return proc


def wait_pending(hub, n=1, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        p = hub.permissions.pending()
        if len(p) >= n:
            return p
        time.sleep(0.05)
    raise AssertionError("hook 没有登记请求")


@pytest.fixture
def hook_env(tmp_path):
    hub = RemoteHub()
    srv = ShionServer(lambda t, d: None, lambda: "", port=0, hub=hub)
    srv.start()
    yield srv, hub, tmp_path
    srv.stop()


def test_hook_outputs_allow_only_after_the_user_decides(hook_env):
    srv, hub, tmp = hook_env
    proc = start_hook(srv, tmp, perm_input("Bash", command="npm test", description="跑测试"))
    req = wait_pending(hub)[0]
    assert req.tool == "Bash" and req.detail == "npm test\n# 跑测试"
    time.sleep(0.5)
    assert proc.poll() is None  # 用户没点之前，hook 一直等，不会自己给决定
    hub.permissions.decide(req.id, True)
    out, err = proc.communicate(timeout=15)
    assert proc.returncode == 0 and err == b""
    assert json.loads(out.decode("utf-8")) == {"hookSpecificOutput": {
        "hookEventName": "PermissionRequest", "decision": {"behavior": "allow"},
    }}


def test_hook_outputs_deny_with_reason(hook_env):
    srv, hub, tmp = hook_env
    proc = start_hook(srv, tmp, perm_input())
    hub.permissions.decide(wait_pending(hub)[0].id, False)
    out, _ = proc.communicate(timeout=15)
    assert json.loads(out.decode("utf-8")) == {"hookSpecificOutput": {
        "hookEventName": "PermissionRequest", "decision": {"behavior": "deny", "message": DENY_ZH},
    }}


@pytest.mark.parametrize("lang,text", [
    ("en", "The user denied this action through Shion."), ("ja", "ユーザーが詩音からこの操作を拒否しました"),
])
def test_deny_message_follows_saved_language(hook_env, lang, text):
    srv, hub, tmp = hook_env
    (tmp / "state.json").write_text(json.dumps({"language": lang}), encoding="utf-8")
    proc = start_hook(srv, tmp, perm_input())
    hub.permissions.decide(wait_pending(hub)[0].id, False)
    out, _ = proc.communicate(timeout=15)
    assert json.loads(out.decode("utf-8"))["hookSpecificOutput"]["decision"]["message"] == text


def test_hook_gives_no_decision_when_shion_is_not_running(tmp_path):
    t0 = time.monotonic()
    r = run_hook("PermissionRequest", 1, tmp_path, stdin=perm_input())
    assert r.returncode == 0 and r.stdout == b"" and r.stderr == b""
    assert time.monotonic() - t0 < 10


def test_hook_times_out_without_any_decision_and_withdraws(hook_env, monkeypatch):
    srv, hub, tmp = hook_env
    monkeypatch.setenv("SHION_PORT", str(srv.port))
    h = load_hook()
    t0 = time.monotonic()
    assert h.permission_decision(json.loads(perm_input()), 0.6, poll=0.2) is None
    assert time.monotonic() - t0 < 5
    assert hub.permissions.pending() == []  # 已撤回，诗音上的面板也会消失


def test_hook_default_timeout_comes_from_save_and_is_clamped(tmp_path, monkeypatch):
    monkeypatch.setenv("SHION_DATA_DIR", str(tmp_path))
    h = load_hook()
    assert h.permission_limit() == 120
    for value, expected in ((60, 60), (1, 10), (9999, 170), ("x", 120), (True, 120)):
        (tmp_path / "state.json").write_text(json.dumps({"remote": {"permission_timeout": value}}), encoding="utf-8")
        assert h.permission_limit() == expected


def test_hook_does_not_handle_ask_user_question(hook_env):
    srv, hub, tmp = hook_env
    r = run_hook("PermissionRequest", srv.port, tmp, stdin=perm_input("AskUserQuestion", questions=[]))
    assert r.returncode == 0 and r.stdout == b""
    assert hub.permissions.pending() == []


@pytest.mark.parametrize("tool_input", [{}, {"plan": "私密计划" * 10000}, {"plan": "短计划", "allowedPrompts": []}])
def test_exit_plan_mode_only_sends_reminder_without_registering_or_deciding(env, tmp_path, tool_input):
    events = []
    hub = env.ctl.hub
    existing = hub.permissions.open("Bash", "echo keep")

    def forward(kind, detail):
        events.append((kind, detail))

    srv = ShionServer(forward, lambda: "", port=0, hub=hub)
    srv.start()
    try:
        payload = json.dumps({"tool_name": "ExitPlanMode", "tool_input": tool_input}).encode("utf-8")
        r = run_hook("PermissionRequest", srv.port, tmp_path, stdin=payload)
        assert r.returncode == 0 and r.stdout == r.stderr == b""
        assert events == [("plan_ready", None)]
        assert [p.id for p in hub.permissions.pending()] == [existing]
        hub.permissions.withdraw(existing)
        # GUI 线程处理实际 hook 发来的事件，不伪造点击。
        env.ctl.handle_event(*events[0])
        env.ctl.tick()
        assert env.ctl._perm_panel is None
        assert env.said[-1] == "计划写好啦，去看看吧～"
        assert env.win.motion_active
    finally:
        srv.stop()


@pytest.mark.parametrize("answer", [None, {"id": "x", "status": "allow"}, {"behavior": "deny"}])
def test_exit_plan_mode_never_calls_permission_routes_or_describes_plan(monkeypatch, answer):
    h = load_hook()
    calls = []
    def request(path, payload=None, timeout=0.5):
        calls.append((path, payload))
        return answer
    def unexpected(*args, **kwargs):
        pytest.fail("ExitPlanMode 不应处理计划内容")
    monkeypatch.setattr(h, "request", request)
    monkeypatch.setattr(h, "describe_permission", unexpected)
    assert h.permission_decision({"tool_name": "ExitPlanMode", "tool_input": {"plan": "私密计划"}}, 0) is None
    assert calls == [("/event", {"type": "plan_ready"})]


def test_exit_plan_mode_without_server_still_returns_no_decision(tmp_path):
    r = run_hook("PermissionRequest", 1, tmp_path, stdin=perm_input("ExitPlanMode", plan="私密计划"))
    assert r.returncode == 0 and r.stdout == r.stderr == b""


@pytest.mark.parametrize("data", [b"", b"[]", b"not json", b"{}", b'{"tool_name": 5}', b'{"tool_name": ""}'])
def test_hook_bad_input_gives_no_decision(hook_env, data):
    srv, hub, tmp = hook_env
    r = run_hook("PermissionRequest", srv.port, tmp, stdin=data)
    assert r.returncode == 0 and r.stdout == b"" and r.stderr == b""
    assert hub.permissions.pending() == []


def test_hook_only_exact_allow_from_matching_id_counts(monkeypatch, tmp_path):
    monkeypatch.setenv("SHION_DATA_DIR", str(tmp_path))  # 不读真实存档的语言
    h = load_hook()
    data = json.loads(perm_input())
    good = {"id": "abc", "status": "allow"}
    cases = [
        (good, {"behavior": "allow"}),
        ({"id": "abc", "status": "deny"}, {"behavior": "deny", "message": DENY_ZH}),
        ({"id": "abc", "status": "gone"}, None),
        ({"id": "abc", "status": "ALLOW"}, None),
        ({"id": "abc", "status": "allowed"}, None),
        ({"id": "abc", "status": True}, None),
        ({"id": "abc", "status": ["allow"]}, None),
        ({"id": "abc"}, None),
        ({"id": "zzz", "status": "allow"}, None),  # id 对不上
        ({"status": "allow"}, None),
        (None, None), ([], None), ("allow", None), ({"allow": True}, None), ({"behavior": "allow"}, None),
    ]
    for answer, expected in cases:
        def fake(path, payload=None, timeout=0.5, _answer=answer):
            return {"id": "abc"} if path == "/permission/open" else (_answer if path == "/permission/wait" else None)
        monkeypatch.setattr(h, "request", fake)
        assert h.permission_decision(data, 5, poll=0.1) == expected, answer


def test_hook_bad_open_response_gives_no_decision(monkeypatch):
    h = load_hook()
    data = json.loads(perm_input())
    for opened in (None, [], {}, {"id": ""}, {"id": 5}, {"id": None}):
        monkeypatch.setattr(h, "request", lambda path, payload=None, timeout=0.5, _o=opened: _o)
        assert h.permission_decision(data, 5, poll=0.1) is None


def test_hook_keeps_waiting_while_pending_then_gives_the_decision(monkeypatch):
    h = load_hook()
    answers = iter([{"id": "abc", "status": "pending"}] * 3 + [{"id": "abc", "status": "allow"}])
    monkeypatch.setattr(h, "request", lambda path, payload=None, timeout=0.5:
                        {"id": "abc"} if path == "/permission/open" else next(answers))
    assert h.permission_decision(json.loads(perm_input()), 5, poll=0.1) == {"behavior": "allow"}


def test_describe_permission_shows_what_will_happen():
    h = load_hook()
    d = h.describe_permission
    assert d("Bash", {"command": "rm -rf build"}) == "rm -rf build"
    assert d("PowerShell", {"command": "ls", "description": "列目录"}) == "ls\n# 列目录"
    assert d("Edit", {"file_path": r"D:\a b\src\state.py", "old_string": "秘密"}) == r"D:\a b\src\state.py"
    assert d("Write", {"file_path": "/tmp/x.txt", "content": "c"}) == "/tmp/x.txt"
    assert d("NotebookEdit", {"notebook_path": "n.ipynb"}) == "n.ipynb"
    assert d("WebFetch", {"url": "https://example.com/a?b=1"}) == "https://example.com/a?b=1"
    assert d("WebSearch", {"query": "pyside6 qtimer"}) == "pyside6 qtimer"
    other = d("mcp__x__tool", {"a": 1, "b": "中文"})
    assert json.loads(other) == {"a": 1, "b": "中文"} and "中文" in other
    assert d("Bash", None) == "{}" and d("Whatever", "not a dict") == "{}"
    assert len(d("Bash", {"command": "x" * 50000})) == 12000


# ---------------------------------------------------------------- 面板和控制器
def open_request(env, detail="git status", tool="Bash", now=None):
    return env.ctl.hub.permissions.open(tool, detail, now)


def test_panel_appears_for_pending_request_and_says_one_line(env):
    assert env.ctl._perm_panel is None
    rid = open_request(env)
    env.advance(0.1)
    panel = env.ctl._perm_panel
    assert panel.isVisible() and panel.request_id == rid
    assert panel._detail.toPlainText() == "git status"
    assert panel._allow.text() == "同意" and panel._deny.text() == "否决"
    assert "[Bash]" in panel._title.text()
    assert env.said[-1] in env.ctl.lines._lines["permission_request"]
    said = len(env.said)
    env.advance(1.0)
    assert len(env.said) == said  # 不会反复说
    env.ctl.hub.permissions.withdraw(rid)
    env.advance(0.2)
    assert not panel.isVisible()


def test_buttons_ignore_clicks_during_arm_delay_then_decide(env):
    rid = open_request(env)
    env.advance(0.1)
    panel = env.ctl._perm_panel
    assert not panel._allow.isEnabled() and not panel._deny.isEnabled()
    panel._click(True)  # 即使事件硬塞进来
    assert env.ctl.hub.permissions.pending()[0].status == "pending"
    env.advance(ARM_DELAY + 0.1)
    panel.refresh_enabled()
    assert panel._allow.isEnabled()
    panel._allow.click()
    assert env.ctl.hub.permissions.wait(rid, 0) == "allow"
    assert not panel.isVisible()  # 没有下一个，面板收起


def test_deny_button_denies(env):
    rid = open_request(env)
    env.advance(0.1)
    env.advance(ARM_DELAY + 0.2)
    env.ctl._perm_panel.refresh_enabled()
    env.ctl._perm_panel._deny.click()
    assert env.ctl.hub.permissions.wait(rid, 0) == "deny"


def test_queue_shows_one_at_a_time_in_order_with_remaining_count(env):
    ids = [open_request(env, f"cmd{i}") for i in range(3)]
    env.advance(0.1)
    panel = env.ctl._perm_panel
    assert panel.request_id == ids[0] and panel._more_label.text() == "还有 2 个"
    assert panel._detail.toPlainText() == "cmd0"
    env.advance(ARM_DELAY + 0.1)
    panel.refresh_enabled()
    panel._allow.click()
    assert panel.request_id == ids[1] and panel._more_label.text() == "还有 1 个"
    assert panel._detail.toPlainText() == "cmd1"
    assert not panel._allow.isEnabled()  # 换成下一条后重新防误点，不会被连点带过
    panel._click(True)
    assert env.ctl.hub.permissions.wait(ids[1], 0) == "pending"
    env.advance(ARM_DELAY + 0.1)
    panel.refresh_enabled()
    panel._deny.click()
    assert panel.request_id == ids[2] and panel._more_label.text() == ""
    assert env.ctl.hub.permissions.wait(ids[0], 0) == "allow"
    assert env.ctl.hub.permissions.wait(ids[1], 0) == "deny"
    assert env.ctl.hub.permissions.wait(ids[2], 0) == "pending"


def test_more_count_updates_when_new_requests_arrive(env):
    open_request(env, "a")
    env.advance(0.1)
    panel = env.ctl._perm_panel
    assert panel._more_label.text() == ""
    open_request(env, "b")
    env.advance(0.1)
    assert panel._more_label.text() == "还有 1 个" and panel._detail.toPlainText() == "a"


def test_unpolled_request_disappears_from_the_panel(env):
    """用户在 CC 里自己答了，CC 杀掉 hook 进程：请求没人轮询，面板自己消失。"""
    open_request(env, "stale", now=time.monotonic() - PENDING_IDLE - 5)
    env.advance(0.2)
    assert env.ctl._perm_panel is None or not env.ctl._perm_panel.isVisible()
    assert env.ctl.hub.permissions.pending() == []
    rid = open_request(env, "next")
    env.advance(0.2)
    assert env.ctl._perm_panel.request_id == rid


def test_panel_does_not_steal_focus_or_react_to_keyboard(env):
    rid = open_request(env)
    env.advance(0.1)
    env.advance(ARM_DELAY + 0.2)
    panel = env.ctl._perm_panel
    panel.refresh_enabled()
    assert panel.windowFlags() & Qt.WindowDoesNotAcceptFocus
    assert panel.testAttribute(Qt.WA_ShowWithoutActivating)
    for w in (panel._allow, panel._deny, panel._detail, panel._toggle):
        assert w.focusPolicy() == Qt.NoFocus
    for key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space, Qt.Key_Y, Qt.Key_A, Qt.Key_Escape):
        QTest.keyClick(panel, key)
        QTest.keyClick(panel._allow, key)
    assert env.ctl.hub.permissions.pending()[0].id == rid  # 键盘一个决定也没产生
    assert env.ctl.hub.permissions.pending()[0].status == "pending"


def test_panel_still_shows_when_bubbles_are_muted(env):
    env.ctl.set_muted(True)
    rid = open_request(env)
    env.advance(0.1)
    assert env.ctl._perm_panel.request_id == rid  # 静音只管说话，不能让人看不到要决定的事
    assert env.said == []


def test_long_text_gets_expand_toggle_and_full_text(env):
    short = open_request(env, "ls")
    env.advance(0.1)
    panel = env.ctl._perm_panel
    assert panel._toggle.isHidden()
    env.ctl.hub.permissions.withdraw(short)
    command = "\n".join(f"echo line {i}" for i in range(40))
    open_request(env, command, tool="Bash")
    env.advance(0.1)
    assert not panel._toggle.isHidden() and panel._toggle.text() == "展开"
    assert panel._detail.toPlainText() == command  # 完整显示，不截断
    h_collapsed = panel.height()
    panel._toggle.click()
    assert panel._toggle.text() == "收起" and panel.height() > h_collapsed
    panel._toggle.click()
    assert panel.height() == h_collapsed


def test_panel_follows_the_pet_and_stays_on_screen(env):
    open_request(env)
    env.advance(0.1)
    panel = env.ctl._perm_panel
    env.win.move(env.win.x() + 40, env.win.y())
    env.ctl._on_window_moved()
    assert panel.isVisible()


def test_texts_in_all_languages_and_no_claude_word(env):
    from shion.lines import LINES_DIR
    for lang in ("zh", "en", "ja"):
        raw = json.loads((LINES_DIR / f"{lang}.json").read_text(encoding="utf-8"))
        for k in ("hook_deny", "permission_title", "permission_allow", "permission_deny", "permission_more",
                  "permission_expand", "permission_collapse"):
            assert raw["ui"][k] and "claude" not in raw["ui"][k].lower()
        assert "{n}" in raw["ui"]["permission_more"]
        assert raw["lines"]["permission_request"]
    env.ctl.set_language("en")
    open_request(env)
    env.advance(0.1)
    panel = env.ctl._perm_panel
    assert (panel._allow.text(), panel._deny.text()) == ("Allow", "Deny")
    assert panel._title.text().startswith("Approve this?")


def test_snapshot_panel_modes_render_png(qapp, tmp_path):
    from shion import app
    from PySide6.QtGui import QImage
    for kind in ("permission", "hold", "input"):
        out = tmp_path / f"{kind}.png"
        assert app.snapshot_panel(str(out), kind, "x\n" * 30, "ja", 2, True) == 0
        img = QImage(str(out))
        assert not img.isNull() and img.width() > 200 and img.height() > 80


def test_hook_gives_no_decision_when_content_is_too_long_to_show_fully(hook_env):
    """内容长到面板放不下时，用户看不全就不能替他决定：不登记请求、不给决定，交回 CC 自己的授权框。"""
    srv, hub, tmp = hook_env
    r = run_hook("PermissionRequest", srv.port, tmp, stdin=perm_input("Bash", command="echo " + "x" * 13000))
    assert r.returncode == 0 and r.stdout == b"" and r.stderr == b""
    assert hub.permissions.pending() == []
    ok = start_hook(srv, tmp, perm_input("Bash", command="echo " + "x" * 5000))
    req = wait_pending(hub)[0]
    assert len(req.detail) == len("echo " + "x" * 5000)  # 没超限的完整显示
    hub.permissions.decide(req.id, True)
    assert b"allow" in ok.communicate(timeout=15)[0]


def test_settings_timeouts_outlast_hook_limits():
    """CC 先杀掉 hook 会变成“超时放行”：settings 里的超时必须大于 hook 自己的最长等待。"""
    import importlib.util
    tools = Path(__file__).resolve().parent.parent / "tools" / "hooks_config.py"
    spec = importlib.util.spec_from_file_location("hc_t", tools)
    hc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hc)
    h = load_hook()
    assert hc.TIMEOUTS["PreToolUse"] >= 1880 + 15  # 暂停上限最大 1880 秒 + 余量
    assert hc.TIMEOUTS["PermissionRequest"] >= 170 + 10
    assert h.FEEDBACK_TIMEOUT > 1.5  # 大于 bridge 等 GUI 线程的时间
    from shion.bridge import TAKE_TIMEOUT
    assert TAKE_TIMEOUT < h.FEEDBACK_TIMEOUT


# ---------------------------------------------------------------- 用户在 CC 里自己答了：面板马上收起
def test_queue_settle_removes_only_that_sessions_pending_requests():
    q = PermissionQueue()
    a1 = q.open("Bash", "ls", session="a", key="k1")
    a2 = q.open("Bash", "pwd", session="a", key="k2")
    b = q.open("Bash", "ls", session="b", key="k1")
    old = q.open("Bash", "ls")  # 旧 hook：没有会话信息，永远不会被 settle 撤掉
    assert q.settle("a", "k1") == 1
    assert [r.id for r in q.pending()] == [a2, b, old]
    assert q.settle("a") == 1 and [r.id for r in q.pending()] == [b, old]
    assert q.settle("") == 0 and q.settle("zzz") == 0
    assert q.wait(a1, 0) == "gone" and q.wait(a2, 0) == "gone"  # 不是决定：hook 不会输出任何东西


def test_queue_settle_never_touches_decided_requests():
    q = PermissionQueue()
    rid = q.open("Bash", "ls", session="a", key="k")
    q.decide(rid, True)
    assert q.settle("a") == 0
    assert q.wait(rid, 0) == "allow"


def test_http_open_records_session_and_key(server):
    srv, _, hub = server
    assert post(srv, "/permission/open", {"tool": "Bash", "detail": "x", "session": "s1", "key": "ab12"})[0] == 200
    req = hub.permissions.pending()[0]
    assert (req.session, req.key) == ("s1", "ab12")


@pytest.mark.parametrize("bad", [{"session": ""}, {"session": 5}, {"session": "x" * 129},
                                 {"key": "XYZ"}, {"key": "a" * 65}, {"key": 3}])
def test_http_open_and_settle_validate_fields(server, bad):
    srv, _, hub = server
    assert post(srv, "/permission/open", {"tool": "Bash", "detail": "x", **bad})[0] == 400
    assert post(srv, "/permission/settle", {"session": "s1", **bad})[0] == 400
    assert hub.permissions.pending() == []


def test_http_settle_requires_a_session(server):
    srv, _, _ = server
    assert post(srv, "/permission/settle", {})[0] == 400
    assert post(srv, "/permission/settle", {"key": "ab"})[0] == 400


def test_http_settle_by_key(server):
    srv, _, hub = server
    keep = hub.permissions.open("Bash", "other", session="s1", key="bb")
    gone = hub.permissions.open("Bash", "ls", session="s1", key="aa")
    assert post(srv, "/permission/settle", {"session": "s1", "key": "aa"}) == (200, {"settled": 1})
    assert [r.id for r in hub.permissions.pending()] == [keep]
    assert post(srv, "/permission/wait", {"id": gone, "wait": 0})[1]["status"] == "gone"


@pytest.mark.parametrize("event", [{"type": "prompt"}, {"type": "stop"},
                                   {"type": "notification", "detail": "idle_prompt"}])
def test_turn_events_settle_that_sessions_requests(server, event):
    srv, _, hub = server
    hub.permissions.open("Bash", "ls", session="s1", key="aa")
    other = hub.permissions.open("Bash", "ls", session="s2", key="aa")
    post(srv, "/event", {**event, "session": "s1"})  # 这里的回调只收两个参数（500），撤请求在回调之前
    assert [r.id for r in hub.permissions.pending()] == [other]


@pytest.mark.parametrize("event", [{"type": "working"}, {"type": "tool_done"},
                                   {"type": "notification", "detail": "permission_prompt"},
                                   {"type": "notification"}])
def test_other_events_keep_requests(server, event):
    srv, _, hub = server
    hub.permissions.open("Bash", "ls", session="s1", key="aa")
    post(srv, "/event", {**event, "session": "s1"})
    assert len(hub.permissions.pending()) == 1


def test_permission_key_matches_between_request_and_post_tool_use():
    hook = load_hook()
    a = hook.permission_key("Bash", {"command": "ls", "description": "列目录"})
    b = hook.permission_key("Bash", {"description": "列目录", "command": "ls"})  # 键顺序无关
    assert a == b and re.fullmatch(r"[0-9a-f]{32}", a)
    assert hook.permission_key("Bash", {"command": "pwd"}) != a
    assert hook.permission_key("PowerShell", {"command": "ls"}) != a


def test_hook_registers_session_and_key(hook_env):
    srv, hub, tmp = hook_env
    stdin = json.dumps({"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "npm test"}}).encode()
    proc = start_hook(srv, tmp, stdin)
    req = wait_pending(hub)[0]
    assert req.session == "s1" and req.key == load_hook().permission_key("Bash", {"command": "npm test"})
    hub.permissions.withdraw(req.id)
    proc.communicate(timeout=15)


@pytest.mark.parametrize("name, extra", [("PostToolUse", {}), ("PostToolUseFailure", {}),
                                         ("PostToolUseFailure", {"is_interrupt": True})])
def test_answering_in_cc_makes_the_waiting_hook_give_no_decision(hook_env, name, extra):
    """CC 里自己答了 → 工具跑完 → 同会话、同工具同参数的 PostToolUse(Failure) 撤掉请求；
    还在等的 PermissionRequest hook 拿到 gone，不输出任何决定。"""
    srv, hub, tmp = hook_env
    ti = {"command": "npm test"}
    perm = start_hook(srv, tmp, json.dumps({"session_id": "s1", "tool_name": "Bash", "tool_input": ti}).encode())
    wait_pending(hub)
    other = hub.permissions.open("Bash", "x", session="s1", key=load_hook().permission_key("Bash", {"command": "x"}))
    post_hook = start_hook(srv, tmp, json.dumps({"session_id": "s1", "tool_name": "Bash", "tool_input": ti,
                                                 "tool_use_id": "t1", **extra}).encode(), name=name)
    post_hook.communicate(timeout=15)
    assert [r.id for r in hub.permissions.pending()] == [other]  # 别的请求还在
    out, err = perm.communicate(timeout=20)
    assert perm.returncode == 0 and out == b"" and err == b""


def test_settled_request_closes_the_panel_and_shows_the_next(env):
    first = env.ctl.hub.permissions.open("Bash", "ls", session="s1", key="aa")
    env.advance(0.1)
    assert env.ctl._perm_panel.request_id == first
    nxt = env.ctl.hub.permissions.open("Bash", "pwd", session="s2", key="bb")
    env.ctl.hub.permissions.settle("s1", "aa")
    env.advance(0.15)
    assert env.ctl._perm_panel.isVisible() and env.ctl._perm_panel.request_id == nxt
    env.ctl.hub.permissions.settle("s2")
    env.advance(0.15)
    assert not env.ctl._perm_panel.isVisible()


def test_panel_title_is_plain_text(qapp):  # noqa: F811
    panel = PermissionPanel()
    texts = {"title": "要执行", "allow": "同意", "deny": "否决", "more": "还有 {n} 条",
             "expand": "展开", "collapse": "收起"}
    panel.show_request("r1", "<b>x</b>", "ls", 0, texts, (0, 0, 100, 100))
    assert panel._title.textFormat() == Qt.PlainText
    assert "<b>x</b>" in panel._title.text()
    panel.close()
