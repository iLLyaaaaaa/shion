"""工作遥控：“停下”→ 检查点原地等待 → 面板选“继续 / 结束这一轮”。"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from shion.lines import LINES_DIR
from shion.panel import ARM_DELAY
from shion.remote import HOLD_GRACE, RemoteHub
from shion.server import ShionServer
from tests.test_controller import env, qapp, find_action  # noqa: F401
from tests.test_hook import HOOK, PRAISE_LINE, run_hook
from tests.test_hook import env as hook_env  # noqa: F401

STOPPED = "已经停下了，在 CC 里说一声就能继续"
STOPPED_TIMEOUT = "等了好久没选，这一轮先结束了；在 CC 里说一声就能继续"
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
    server = ShionServer(lambda t, d: events.append((t, d)), lambda: "", port=0, hub=hub)
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


def armed(pet):
    pet.advance(ARM_DELAY + 0.1)
    panel = pet.ctl._hold_panel
    panel.refresh_enabled()
    return panel


def remote_texts(pet):
    menu = pet.ctl.build_menu()  # 留着引用：顶层菜单被回收时子菜单的动作也会被销毁
    remote = find_action(menu, "工作遥控").menu()
    return menu, remote, [(a.text(), a.isEnabled()) for a in remote.actions()]


def test_menu_has_only_stop_and_shows_pending(pet):
    menu, remote, texts = remote_texts(pet)
    assert texts == [("停下", True), ("做得好", True), ("有问题……", True)]
    find_action(remote, "停下").trigger()
    assert pet.ctl.hub.is_paused and pet.state.paused
    assert pet.said[-1] == "好，下一个空当就停下～"
    assert pet.win.sprite_name == "stop"
    _, _, texts2 = remote_texts(pet)
    assert texts2[0] == ("正在停下……", False)
    assert len(texts2) == 3


def test_panel_waits_for_a_hook_at_the_checkpoint(pet):
    pet.ctl.stop_work()
    pet.advance(1.0)
    assert pet.ctl._hold_panel is None  # 还没到检查点：只有气泡
    threads, _ = start_waiters(pet.ctl.hub)
    pet.advance(0.1)
    panel = pet.ctl._hold_panel
    assert panel.isVisible() and panel.is_open
    assert (panel._title.text(), panel._continue.text(), panel._end.text()) == (
        "停在这儿等你决定～", "继续", "结束这一轮")
    pet.ctl.hub.resume()
    join(threads)


def test_continue_releases_hook_seamlessly(pet):
    threads, results = held(pet)
    panel = pet.ctl._hold_panel
    assert not panel._continue.isEnabled()
    panel._click("continue")  # 0.6 秒内硬塞进来的点击也不算
    assert pet.ctl.hub.is_paused
    armed(pet)._continue.click()
    join(threads)
    assert results == [(False, False)]
    assert not pet.state.paused and not panel.isVisible()
    assert pet.said[-1] in pet.ctl.lines._lines["resumed"]
    assert pet.win.sprite_name != "stop"
    assert remote_texts(pet)[2][0] == ("停下", True)


def test_end_round_stops_every_waiting_hook_and_shows_sticky_notice(pet):
    pet.data.activity_level = "quiet"
    threads, results = held(pet, n=3)
    armed(pet)._end.click()
    join(threads)
    assert results == [(False, True)] * 3
    for _ in range(3):  # 每个 hook 都报一次，只处理第一次
        pet.ctl.handle_event("work_stopped")
    assert pet.sticky == [STOPPED]
    assert not pet.state.paused and not pet.ctl._hold_panel.isVisible()
    for _ in range(30):
        pet.advance(1.0)
    assert pet.sticky == [STOPPED]
    pet.ctl.handle_event("prompt")
    pet.advance(5.0)
    assert pet.sticky == [STOPPED]  # 在 CC 里说话后不再冒出来
    assert not pet.ctl._work_stopped


def test_prompt_from_cc_releases_wait_and_closes_panel(pet):
    threads, results = held(pet)
    pet.ctl.hub.resume()  # 服务线程收到 prompt 事件时做的
    pet.ctl.handle_event("prompt")
    join(threads)
    assert results == [(False, False)]
    assert not pet.state.paused and not pet.ctl._hold_panel.isVisible()


def test_timeout_is_treated_as_end_round(pet):
    pet.data.activity_level = "quiet"
    threads, results = held(pet, n=2)
    pet.ctl.handle_event("pause_timeout")  # 一个 hook 等满上限
    join(threads)
    assert results == [(False, True)] * 2  # 其余并行等待的也一起结束
    assert pet.sticky == [STOPPED_TIMEOUT]
    assert not pet.state.paused and not pet.ctl._hold_panel.isVisible()


def test_timeout_ignored_when_not_stopping(pet):
    pet.ctl.handle_event("pause_timeout")
    assert pet.sticky == [] and not pet.state.paused and not pet.ctl._work_stopped


def test_turn_ending_before_checkpoint_cancels_stop(pet):
    pet.ctl.stop_work()
    pet.ctl.hub.resume()  # 服务线程收到 Stop 且没人在等时做的
    pet.ctl.handle_event("stop")
    assert not pet.state.paused and pet.win.sprite_name != "stop"
    assert remote_texts(pet)[2][0] == ("停下", True)


def test_panel_closes_when_hook_goes_away_and_returns_if_it_comes_back(pet):
    pet.ctl.stop_work()
    hub = pet.ctl.hub
    threads, results = start_waiters(hub, seconds=0.3)  # hook 被 CC 杀掉 ≈ 不再来轮询
    pet.advance(0.1)
    assert pet.ctl._hold_panel.isVisible()
    join(threads)
    assert results == [(True, False)]
    hub._last_hold -= HOLD_GRACE + 0.1
    pet.advance(0.1)
    assert not pet.ctl._hold_panel.isVisible() and pet.state.paused
    threads, _ = start_waiters(hub)
    pet.advance(0.1)
    assert pet.ctl._hold_panel.isVisible()
    hub.resume()
    join(threads)


def test_permission_panel_takes_priority(pet):
    threads, _ = held(pet)
    rid = pet.ctl.hub.permissions.open("Bash", "ls")
    pet.advance(0.1)
    assert pet.ctl._perm_panel.isVisible() and not pet.ctl._hold_panel.isVisible()
    pet.ctl.hub.permissions.withdraw(rid)
    pet.advance(0.1)
    assert pet.ctl._hold_panel.isVisible()
    pet.ctl.hub.resume()
    join(threads)


def test_panel_does_not_steal_focus_or_react_to_keyboard(pet):
    threads, _ = held(pet)
    panel = armed(pet)
    assert panel.windowFlags() & Qt.WindowDoesNotAcceptFocus
    assert panel.testAttribute(Qt.WA_ShowWithoutActivating)
    for w in (panel._continue, panel._end):
        assert w.focusPolicy() == Qt.NoFocus
    for key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space, Qt.Key_Escape, Qt.Key_Y):
        QTest.keyClick(panel, key)
        QTest.keyClick(panel._continue, key)
        QTest.keyClick(panel._end, key)
    assert pet.ctl.hub.is_paused and pet.state.paused  # 键盘一个决定也没产生
    pet.ctl.hub.resume()
    join(threads)


def test_panel_follows_the_pet_and_closes_dialogue(pet):
    pet.ctl.open_dialogue()
    assert pet.ctl._dialogue.isVisible()
    threads, _ = held(pet)
    assert not pet.ctl._dialogue.isVisible()
    pet.ctl.open_dialogue()  # 面板开着时不能打开对话
    assert not pet.ctl._dialogue.isVisible()
    pet.win.move(pet.win.x() + 40, pet.win.y())
    pet.ctl._on_window_moved()
    assert pet.ctl._hold_panel.isVisible()
    pet.ctl.hub.resume()
    join(threads)


def test_muted_still_stops_and_shows_panel(pet):
    pet.ctl.set_muted(True)
    threads, results = held(pet)
    assert pet.ctl._hold_panel.isVisible()
    armed(pet)._end.click()
    join(threads)
    assert results == [(False, True)] and pet.said == []


def test_panel_text_is_localized(pet):
    pet.ctl.set_language("en")
    threads, _ = held(pet)
    panel = pet.ctl._hold_panel
    assert (panel._continue.text(), panel._end.text()) == ("Continue", "End this turn")
    pet.ctl.hub.resume()
    join(threads)


def test_stop_texts_in_all_languages_never_mention_claude():
    keys = ("menu_stop", "menu_stop_pending", "stop_requested", "work_stopped", "work_stopped_timeout",
            "hook_stop", "hook_stop_timeout", "hold_title", "hold_continue", "hold_end")
    for lang in ("zh", "en", "ja"):
        raw = json.loads((LINES_DIR / f"{lang}.json").read_text(encoding="utf-8"))
        for k in keys:
            assert raw["ui"][k] and "claude" not in raw["ui"][k].lower()
        for k in ("menu_pause", "menu_resume", "paused_status", "paused_timeout"):
            assert k not in raw["ui"]
