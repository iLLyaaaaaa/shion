"""工作遥控：“停下”→ 检查点原地等待 → 菜单“继续”放行 / 在 CC 里说话放行 / 等满上限结束这一轮。"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest
from shion.lines import LINES_DIR
from shion.remote import HOLD_GRACE, RemoteHub
from shion.server import ShionServer
from tests.test_controller import env, qapp, find_action  # noqa: F401
from tests.test_hook import HOOK, PRAISE_LINE, run_hook
from tests.test_hook import env as hook_env  # noqa: F401

STOP_REQUESTED = "好，马上停～"
HELD = "已经停下啦～"
STOPPED_TIMEOUT = "停太久了，这一轮先结束啦，在 CC 里说一声就能接着做"
STOP_REASON = "用户通过诗音让这一轮工作停下，请等待用户指示"
TIMEOUT_REASON = "用户很久没有回应，这一轮先结束，请等待用户指示"


def start_waiters(hub, n=1, seconds=5.0):
    """模拟 n 个在检查点长轮询的 hook。返回 (线程, 结果列表)。"""
    results = []
    threads = [threading.Thread(target=lambda: results.append(hub.wait_gate(seconds)), daemon=True)
               for _ in range(n)]
    for t in threads:
        t.start()
    deadline = time.monotonic() + 3
    while hub._holding < n and time.monotonic() < deadline:
        time.sleep(0.01)
    return threads, results


def join(threads):
    for t in threads:
        t.join(5)


# ---------------------------------------------------------------- RemoteHub
def test_wait_gate_passes_immediately_when_not_paused():
    hub = RemoteHub()
    assert hub.wait_gate(5) == (False, False)
    assert not hub.is_holding


def test_resume_releases_waiter_without_stop():
    hub = RemoteHub()
    hub.pause()
    threads, results = start_waiters(hub)
    assert hub.is_holding
    hub.resume()
    join(threads)
    assert results == [(False, False)]


def test_end_releases_all_parallel_waiters_with_stop_and_leaves_nothing_behind():
    hub = RemoteHub()
    hub.pause()
    threads, results = start_waiters(hub, n=4)
    hub.end()
    join(threads)
    assert results == [(False, True)] * 4
    assert not hub.is_paused
    assert hub.wait_gate(0) == (False, False)  # 之后才到的 hook 不受影响
    hub.pause()
    assert hub.wait_gate(0.1) == (True, False)  # 下一次停下也不会被上一次的“结束”带过


def test_waiter_times_out_still_paused():
    hub = RemoteHub()
    hub.pause()
    t0 = time.monotonic()
    assert hub.wait_gate(0.2) == (True, False)
    assert time.monotonic() - t0 < 2


def test_is_holding_has_short_grace_between_polls():
    hub = RemoteHub()
    hub.pause()
    hub.wait_gate(0.05)
    assert hub._holding == 0 and hub.is_holding  # 两段长轮询之间的空当仍算在等
    hub._last_hold -= HOLD_GRACE + 0.1
    assert not hub.is_holding


# ---------------------------------------------------------------- HTTP 服务
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
    server = ShionServer(lambda t, d, m=None: events.append((t, d)), lambda: "", port=0, hub=hub)
    server.start()
    yield server, hub, events
    hub.resume()
    server.stop()


def test_pause_wait_reports_end_and_notifies(srv):
    server, hub, events = srv
    hub.pause()
    threading.Timer(0.3, hub.end).start()
    assert _post(server.port, "/pause/wait", {"wait": 5}) == {"paused": False, "stop": True}
    assert events == [("work_stopped", None)]
    assert _post(server.port, "/pause/wait", {"wait": 0}) == {"paused": False, "stop": False}


def test_http_cannot_stop_or_fake_stopped(srv):
    server, hub, events = srv
    for path in ("/pause/wait", "/event", "/feedback/take", "/permission/wait"):
        for body in ({"stop": True}, {"type": "stop_work"}, {"continue": False}, {"type": "pause"},
                     {"type": "end"}):
            try:
                _post(server.port, path, body)
            except urllib.error.HTTPError:
                pass
    assert not hub.is_paused
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(server.port, "/event", {"type": "work_stopped"})
    assert e.value.code == 400
    assert ("work_stopped", None) not in events


def test_turn_end_before_checkpoint_cancels_unused_stop(srv):
    server, hub, _ = srv
    hub.pause()
    _post(server.port, "/event", {"type": "stop"})
    assert not hub.is_paused


def test_turn_end_from_elsewhere_does_not_release_a_waiting_hook(srv):
    server, hub, _ = srv
    hub.pause()
    threads, results = start_waiters(hub, seconds=1.0)
    _post(server.port, "/event", {"type": "stop"})  # 比如另一个会话结束了
    assert hub.is_paused
    join(threads)
    assert results == [(True, False)]


def test_prompt_releases_waiting_hook(srv):
    server, hub, _ = srv
    hub.pause()
    threads, results = start_waiters(hub)
    _post(server.port, "/event", {"type": "prompt"})
    join(threads)
    assert results == [(False, False)]


# ---------------------------------------------------------------- hook 脚本
def run_hook_main(server, tmp, name, limit):
    code = (
        "import sys, importlib.util;"
        f"spec = importlib.util.spec_from_file_location('h', {str(HOOK)!r});"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m);"
        f"m.pause_limit = lambda: {limit}; sys.argv = ['x', {name!r}]; m.main()"
    )
    return subprocess.run(
        [sys.executable, "-c", code], input=b"{}", capture_output=True, timeout=20,
        env={**os.environ, "SHION_PORT": str(server.port), "SHION_DATA_DIR": str(tmp)},
    )


def test_post_tool_use_waits_then_continue_delivers_feedback(hook_env):  # noqa: F811
    server, events, state, tmp = hook_env
    server.hub.pause()
    state["feedback"] = PRAISE_LINE
    seen = []

    def resume():
        seen.append(state["feedback"])  # 等待期间没取反馈
        server.hub.resume()

    threading.Timer(1.0, resume).start()
    t0 = time.monotonic()
    r = run_hook("PostToolUse", server.port, tmp)
    assert time.monotonic() - t0 >= 0.9
    assert seen == [PRAISE_LINE]
    out = json.loads(r.stdout.decode("utf-8"))
    assert out["hookSpecificOutput"]["additionalContext"] == PRAISE_LINE


def test_pre_tool_use_continue_lets_tool_run(hook_env):  # noqa: F811
    server, events, _, tmp = hook_env
    server.hub.pause()
    threading.Timer(1.0, server.hub.resume).start()
    r = run_hook("PreToolUse", server.port, tmp, stdin=json.dumps({"tool_name": "Read"}).encode())
    assert r.returncode == 0 and r.stdout == b""
    assert any(t == "working" for t, _ in events)


@pytest.mark.parametrize("name", ["PreToolUse", "PostToolUse"])
def test_end_round_ends_turn_with_continue_false(hook_env, name):  # noqa: F811
    server, events, state, tmp = hook_env
    state["feedback"] = PRAISE_LINE
    server.hub.pause()
    threading.Timer(1.0, server.hub.end).start()
    r = run_hook(name, server.port, tmp, stdin=json.dumps({"tool_name": "Read"}).encode())
    out = json.loads(r.stdout.decode("utf-8"))
    assert out["continue"] is False and out["stopReason"] == STOP_REASON
    if name == "PreToolUse":
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert not any(t == "working" for t, _ in events)
    else:
        assert "hookSpecificOutput" not in out
        assert state["feedback"] == PRAISE_LINE  # 结束时反馈留到下一次
    assert ("work_stopped", None) in events
    r2 = run_hook(name, server.port, tmp)  # 之后的检查点直接放行
    assert b"continue" not in r2.stdout


def test_stop_reason_follows_save_language(hook_env):  # noqa: F811
    server, _, _, tmp = hook_env
    (tmp / "state.json").write_text(json.dumps({"language": "en"}), encoding="utf-8")
    server.hub.pause()
    threading.Timer(0.5, server.hub.end).start()
    r = run_hook("PostToolUse", server.port, tmp)
    reason = json.loads(r.stdout.decode("utf-8"))["stopReason"]
    assert reason.startswith("The user stopped this turn") and "claude" not in reason.lower()


def test_post_tool_use_timeout_ends_turn(hook_env):  # noqa: F811
    server, events, _, tmp = hook_env
    server.hub.pause()
    r = run_hook_main(server, tmp, "PostToolUse", limit=1)
    assert json.loads(r.stdout.decode("utf-8")) == {"continue": False, "stopReason": TIMEOUT_REASON}
    assert ("pause_timeout", None) in events


@pytest.mark.parametrize("name", ["PreToolUse", "PostToolUse"])
def test_checkpoint_server_down_is_silent_and_fast(tmp_path, name):
    t0 = time.monotonic()
    r = run_hook(name, 1, tmp_path)
    assert r.returncode == 0 and r.stdout == b"" and time.monotonic() - t0 < 5


# ---------------------------------------------------------------- 控制器
@pytest.fixture
def pet(env):  # noqa: F811
    env.sticky = []

    def say(text, sticky=False):
        env.said.append(text)
        if sticky:
            env.sticky.append(text)

    env.ctl._say_fn = say
    yield env
    env.ctl.hub.resume()


def held(pet, n=1):
    """点“停下”，再让 n 个 hook 到达检查点；返回 (线程, 结果)。"""
    pet.ctl.stop_work()
    threads, results = start_waiters(pet.ctl.hub, n=n)
    pet.advance(0.1)
    return threads, results


def remote_texts(pet):
    menu = pet.ctl.build_menu()  # 留着引用：顶层菜单被回收时子菜单的动作也会被销毁
    remote = find_action(menu, "工作遥控").menu()
    return menu, remote, [(a.text(), a.isEnabled()) for a in remote.actions()]


def test_menu_stop_turns_into_continue(pet):
    menu, remote, texts = remote_texts(pet)
    assert texts == [("停下", True), ("立即中断", False), ("做得好", True), ("有问题……", True)]
    find_action(remote, "停下").trigger()
    assert pet.ctl.hub.is_paused and pet.state.paused
    assert pet.said[-1] == STOP_REQUESTED
    assert pet.win.sprite_name == "stop"
    _, _, texts2 = remote_texts(pet)
    assert texts2[0] == ("继续", True)
    assert len(texts2) == 4


def test_held_notice_is_said_once_when_a_hook_really_waits(pet):
    pet.ctl.stop_work()
    pet.advance(1.0)
    assert pet.said == [STOP_REQUESTED]  # 还没到检查点
    threads, _ = start_waiters(pet.ctl.hub, n=3)
    for _ in range(30):
        pet.advance(0.2)
    assert pet.said == [STOP_REQUESTED, HELD]  # 三个并行 hook、多次轮询，只说一次
    assert pet.sticky == []  # 不常驻
    pet.ctl.hub.resume()
    join(threads)


def test_menu_continue_releases_hook(pet):
    threads, results = held(pet)
    _, remote, _ = remote_texts(pet)
    menu, remote, _ = remote_texts(pet)
    find_action(remote, "继续").trigger()
    join(threads)
    assert results == [(False, False)]
    assert not pet.state.paused and not pet.ctl.hub.is_paused
    assert pet.said[-1] in pet.ctl.lines._lines["resumed"]
    assert pet.win.sprite_name != "stop"
    assert remote_texts(pet)[2][0] == ("停下", True)


def test_continue_before_checkpoint_cancels_stop(pet):
    pet.ctl.stop_work()
    pet.ctl.resume_work()
    assert not pet.ctl.hub.is_paused and not pet.state.paused
    assert pet.ctl.hub.wait_gate(0) == (False, False)


def test_prompt_from_cc_releases_wait(pet):
    threads, results = held(pet)
    pet.ctl.hub.resume()  # 服务线程收到 prompt 事件时做的
    pet.ctl.handle_event("prompt")
    join(threads)
    assert results == [(False, False)]
    assert not pet.state.paused
    pet.ctl.stop_work()  # 下一次停下又能说“已经停下啦”
    threads, _ = start_waiters(pet.ctl.hub)
    pet.advance(0.1)
    assert pet.said.count(HELD) == 2
    pet.ctl.hub.resume()
    join(threads)


def test_timeout_ends_every_waiting_hook_and_says_once(pet):
    pet.data.activity_level = "quiet"
    threads, results = held(pet, n=2)
    pet.ctl.handle_event("pause_timeout")  # 一个 hook 等满上限
    pet.ctl.handle_event("pause_timeout")  # 另一个也报：不再重复
    join(threads)
    assert results == [(False, True)] * 2  # 其余并行等待的也一起结束
    assert pet.said.count(STOPPED_TIMEOUT) == 1 and pet.sticky == []
    assert not pet.state.paused
    for _ in range(30):
        pet.advance(1.0)
    assert pet.said.count(STOPPED_TIMEOUT) == 1


def test_timeout_ignored_when_not_stopping(pet):
    pet.ctl.handle_event("pause_timeout")
    assert pet.said == [] and not pet.state.paused


def test_turn_ending_before_checkpoint_cancels_stop(pet):
    pet.ctl.stop_work()
    pet.ctl.hub.resume()  # 服务线程收到 Stop 且没人在等时做的
    pet.ctl.handle_event("stop")
    assert not pet.state.paused and pet.win.sprite_name != "stop"
    assert remote_texts(pet)[2][0] == ("停下", True)


def test_no_panel_pops_up_any_more(pet):
    threads, _ = held(pet)
    assert not hasattr(pet.ctl, "_hold_panel")
    pet.ctl.open_dialogue()  # 停下期间也能打开对话
    assert pet.ctl._dialogue.isVisible()
    pet.ctl.hub.resume()
    join(threads)


def test_muted_still_stops_without_speaking(pet):
    pet.ctl.set_muted(True)
    threads, results = held(pet)
    assert pet.ctl.hub.is_paused and pet.said == []
    pet.ctl.resume_work(quiet=True)
    join(threads)
    assert results == [(False, False)]


def test_menu_texts_are_localized(pet):
    pet.ctl.set_language("en")
    menu = pet.ctl.build_menu()
    remote = find_action(menu, "Work remote").menu()
    assert [a.text() for a in remote.actions()][:2] == ["Stop", "Interrupt now"]
    pet.ctl.stop_work()
    menu = pet.ctl.build_menu()
    remote = find_action(menu, "Work remote").menu()
    assert remote.actions()[0].text() == "Continue"


def test_stop_texts_in_all_languages_never_mention_claude():
    keys = ("menu_stop", "menu_resume", "menu_interrupt", "stop_requested", "work_held", "work_stopped_timeout",
            "hook_stop", "hook_stop_timeout", "interrupted", "interrupt_no_process", "interrupt_idle")
    for lang in ("zh", "en", "ja"):
        raw = json.loads((LINES_DIR / f"{lang}.json").read_text(encoding="utf-8"))
        for k in keys:
            assert raw["ui"][k] and "claude" not in raw["ui"][k].lower()
        for k in ("menu_pause", "paused_status", "paused_timeout", "menu_stop_pending", "work_stopped",
                  "hold_title", "hold_continue", "hold_end"):
            assert k not in raw["ui"]
