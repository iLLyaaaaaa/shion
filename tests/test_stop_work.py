"""工作遥控：PostToolUse 暂停检查点和“停下”（continue: false，只生效一次）。"""
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
from shion.remote import RemoteHub
from shion.server import ShionServer
from tests.test_controller import env, qapp, find_action  # noqa: F401
from tests.test_hook import HOOK, PRAISE_LINE, run_hook
from tests.test_hook import env as hook_env  # noqa: F401

STOPPED = "已经停下了，在 CC 里说一声就能继续"
STOP_REASON = "用户通过诗音让这一轮工作停下，请等待用户指示"


# ---------------------------------------------------------------- RemoteHub
def test_wait_gate_hands_out_stop_exactly_once():
    hub = RemoteHub()
    assert hub.wait_gate(0) == (False, False)
    hub.request_stop()
    assert hub.stop_requested
    assert hub.wait_gate(0) == (False, True)
    assert hub.wait_gate(0) == (False, False)  # 只生效一次
    assert not hub.stop_requested


def test_wait_gate_wakes_paused_waiter_on_stop_and_keeps_pause():
    hub = RemoteHub()
    hub.pause()
    threading.Timer(0.3, hub.request_stop).start()
    t0 = time.monotonic()
    assert hub.wait_gate(5) == (True, True)  # 被停下唤醒，暂停标记不变
    assert time.monotonic() - t0 < 3
    assert hub.is_paused and not hub.stop_requested
    assert hub.wait_gate(0.2) == (True, False)


def test_wait_gate_parallel_waiters_only_one_gets_stop():
    hub = RemoteHub()
    hub.pause()
    results = []
    threads = [threading.Thread(target=lambda: results.append(hub.wait_gate(2))) for _ in range(4)]
    for t in threads:
        t.start()
    time.sleep(0.2)
    hub.request_stop()
    for t in threads:
        t.join(5)
    assert len(results) == 4
    assert sum(1 for _, stop in results if stop) == 1


def test_cancel_stop_clears_request():
    hub = RemoteHub()
    hub.request_stop()
    hub.cancel_stop()
    assert hub.wait_gate(0) == (False, False)


# ---------------------------------------------------------------- HTTP 服务
def _post(port, path, body):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


@pytest.fixture
def srv():
    events = []
    hub = RemoteHub()
    server = ShionServer(lambda t, d: events.append((t, d)), lambda: "", port=0, hub=hub)
    server.start()
    yield server, hub, events
    hub.resume()
    server.stop()


def test_pause_wait_hands_out_stop_and_notifies(srv):
    server, hub, events = srv
    assert _post(server.port, "/pause/wait", {"wait": 0}) == {"paused": False, "stop": False}
    hub.request_stop()
    assert _post(server.port, "/pause/wait", {"wait": 0}) == {"paused": False, "stop": True}
    assert events == [("work_stopped", None)]
    assert _post(server.port, "/pause/wait", {"wait": 0}) == {"paused": False, "stop": False}


def test_http_cannot_request_stop_or_fake_stopped(srv):
    server, hub, events = srv
    for path in ("/pause/wait", "/event", "/feedback/take", "/permission/wait"):
        for body in ({"stop": True}, {"type": "stop_work"}, {"continue": False}, {"type": "pause"}):
            try:
                _post(server.port, path, body)
            except urllib.error.HTTPError:
                pass
    assert not hub.stop_requested and not hub.is_paused
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(server.port, "/event", {"type": "work_stopped"})
    assert e.value.code == 400
    assert ("work_stopped", None) not in events


@pytest.mark.parametrize("etype", ["prompt", "stop"])
def test_new_turn_or_turn_end_cancels_unused_stop(srv, etype):
    server, hub, _ = srv
    hub.request_stop()
    _post(server.port, "/event", {"type": etype})
    assert not hub.stop_requested


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


def test_post_tool_use_waits_while_paused_then_delivers_feedback(hook_env):  # noqa: F811
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


@pytest.mark.parametrize("name", ["PreToolUse", "PostToolUse"])
def test_stop_ends_turn_with_continue_false(hook_env, name):  # noqa: F811
    server, events, state, tmp = hook_env
    state["feedback"] = PRAISE_LINE
    server.hub.request_stop()
    r = run_hook(name, server.port, tmp, stdin=json.dumps({"tool_name": "Read"}).encode())
    out = json.loads(r.stdout.decode("utf-8"))
    assert out["continue"] is False and out["stopReason"] == STOP_REASON
    if name == "PreToolUse":
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert not any(t == "working" for t, _ in events)
    else:
        assert "hookSpecificOutput" not in out
        assert state["feedback"] == PRAISE_LINE  # 停下时反馈留到下一次
    assert ("work_stopped", None) in events
    assert not server.hub.stop_requested
    r2 = run_hook(name, server.port, tmp)  # 只生效一次
    assert b"continue" not in r2.stdout


@pytest.mark.parametrize("name", ["PreToolUse", "PostToolUse"])
def test_stop_while_paused_releases_waiting_hook(hook_env, name):  # noqa: F811
    server, _, _, tmp = hook_env
    server.hub.pause()
    threading.Timer(1.0, server.hub.request_stop).start()
    r = run_hook(name, server.port, tmp)
    assert json.loads(r.stdout.decode("utf-8"))["continue"] is False


def test_stop_reason_follows_save_language(hook_env):  # noqa: F811
    server, _, _, tmp = hook_env
    (tmp / "state.json").write_text(json.dumps({"language": "en"}), encoding="utf-8")
    server.hub.request_stop()
    r = run_hook("PostToolUse", server.port, tmp)
    reason = json.loads(r.stdout.decode("utf-8"))["stopReason"]
    assert reason.startswith("The user stopped this turn") and "claude" not in reason.lower()


def test_post_tool_use_pause_timeout_stops_turn(hook_env):  # noqa: F811
    server, events, _, tmp = hook_env
    server.hub.pause()
    r = run_hook_main(server, tmp, "PostToolUse", limit=1)
    assert json.loads(r.stdout.decode("utf-8")) == {
        "continue": False, "stopReason": "用户暂停了工作，请停下并等待用户指示",
    }
    assert ("pause_timeout", None) in events


def test_post_tool_use_server_down_is_silent_and_fast(tmp_path):
    t0 = time.monotonic()
    r = run_hook("PostToolUse", 1, tmp_path)
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
    return env


def test_stop_is_first_in_remote_menu_and_shows_pending(pet):
    menu = pet.ctl.build_menu()  # 留着引用：顶层菜单被回收时子菜单的动作也会被销毁
    remote = find_action(menu, "工作遥控").menu()
    assert remote.actions()[0].text() == "停下工作"
    find_action(remote, "停下工作").trigger()
    assert pet.ctl.hub.stop_requested and not pet.ctl.hub.is_paused
    assert pet.said[-1] == "好，下一个空当就停下～"
    menu2 = pet.ctl.build_menu()
    first = find_action(menu2, "工作遥控").menu().actions()[0]
    assert first.text() == "正在停下……" and not first.isEnabled()


def test_work_stopped_shows_sticky_notice_until_prompt(pet):
    pet.data.activity_level = "quiet"
    pet.ctl.stop_work()
    pet.ctl.hub.wait_gate(0)  # hook 取走了停下
    pet.ctl.handle_event("work_stopped")
    assert pet.sticky == [STOPPED]
    for _ in range(30):
        pet.advance(1.0)
    assert pet.sticky == [STOPPED]
    pet.ctl.handle_event("prompt")
    pet.advance(5.0)
    assert pet.sticky == [STOPPED]  # 不再冒出来
    menu = pet.ctl.build_menu()
    assert find_action(menu, "工作遥控").menu().actions()[0].text() == "停下工作"


def test_work_stopped_while_paused_shows_stopped_notice(pet):
    pet.ctl.pause_work()
    pet.ctl.stop_work()
    pet.ctl.handle_event("work_stopped")
    assert pet.state.paused and pet.sticky[-1] == STOPPED
    pet.ctl.resume_work()
    assert not pet.state.paused and not pet.ctl._work_stopped


def test_muted_stop_still_requests_stop(pet):
    pet.ctl.set_muted(True)
    pet.ctl.stop_work()
    pet.ctl.handle_event("work_stopped")
    assert pet.said == [] and pet.ctl.hub.stop_requested


def test_stop_texts_in_all_languages_never_mention_claude():
    for lang in ("zh", "en", "ja"):
        raw = json.loads((LINES_DIR / f"{lang}.json").read_text(encoding="utf-8"))
        for k in ("menu_stop", "menu_stop_pending", "stop_requested", "work_stopped", "hook_stop"):
            assert raw["ui"][k] and "claude" not in raw["ui"][k].lower()
