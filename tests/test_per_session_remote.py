"""工作遥控按会话区分：停下 / 继续 / 结束这一轮 / 立即中断 / 反馈都能选会话。"""
import importlib.util
import json
import threading
import time
import urllib.request

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from shion.remote import RemoteHub
from shion.server import ShionServer, clean_project, parse_meta
from shion.sessions import SessionNames
from shion.state import PetState, SaveData, _feedback_items
from tests.test_controller import T0, env, find_action, qapp  # noqa: F401
from tests.test_hook import HOOK, run_hook
from tests.link_support import auth
from tests.test_interrupt import CC, START, FakeView, ft
from tests.test_stop_work import join

PRAISE = "[诗音] 用户觉得你刚才做得很好。"


def wait_for(cond, seconds=3.0):
    deadline = time.monotonic() + seconds
    while not cond() and time.monotonic() < deadline:
        time.sleep(0.01)
    return cond()


def waiter(hub, session, seconds=5.0):
    """在检查点长轮询的一个 hook（属于 session）。返回 (线程, 结果列表)。"""
    results = []
    before = hub._holding
    t = threading.Thread(target=lambda: results.append(hub.wait_gate(seconds, session)), daemon=True)
    t.start()
    wait_for(lambda: hub._holding > before)
    return t, results


# ---------------------------------------------------------------- RemoteHub
def test_pausing_a_leaves_b_running():
    hub = RemoteHub()
    hub.pause("A")
    assert hub.wait_gate(5, "B") == (False, False)  # 立即放行
    t, res = waiter(hub, "A")
    assert hub.holding_sessions() == ["A"] and hub.is_session_paused("A") and not hub.is_session_paused("B")
    hub.resume("A")
    join([t])
    assert res == [(False, False)]


def test_ending_a_does_not_touch_b_waiting_hook():
    hub = RemoteHub()
    hub.pause("A")
    hub.pause("B")
    ta, ra = waiter(hub, "A")
    tb, rb = waiter(hub, "B", seconds=1.0)
    hub.end("A")
    join([ta])
    assert ra == [(False, True)]
    assert tb.is_alive() and hub.is_session_paused("B")  # B 还在等
    join([tb])
    assert rb == [(True, False)]  # 等满这一段：仍停着，没有被结束
    assert hub.wait_gate(0, "A") == (False, False)  # “结束这一轮”不留残余


def test_global_pause_then_resume_one_session_keeps_the_other():
    hub = RemoteHub()
    hub.pause()
    for s in ("A", "B"):
        hub.pause(s)  # 多会话菜单的“全部”
    ta, ra = waiter(hub, "A")
    tb, rb = waiter(hub, "B", seconds=1.0)
    hub.resume("A")
    join([ta])
    assert ra == [(False, False)]
    assert hub.is_session_paused("B") and hub.is_global_paused
    hub.resume()
    join([tb])
    assert rb == [(False, False)] and not hub.is_paused


def test_single_session_resume_clears_the_global_pause_like_before():
    hub = RemoteHub()
    hub.pause()  # 只有一个会话时菜单仍是全局停下
    t, _ = waiter(hub, "A")
    hub.resume("A")  # 例如这个会话在 CC 里说了话
    join([t])
    assert not hub.is_paused and not hub.is_global_paused


def test_requests_without_session_follow_only_the_global_pause():
    hub = RemoteHub()
    hub.pause("A")
    assert hub.wait_gate(5, None) == (False, False)
    hub.pause()
    t, res = waiter(hub, None)
    assert hub.holding_sessions() == []  # 旧请求不进会话列表
    hub.end()
    join([t])
    assert res == [(False, True)]


def test_holding_sessions_are_listed_in_order_they_started_waiting():
    hub = RemoteHub()
    hub.pause()
    tb, _ = waiter(hub, "B")
    ta, _ = waiter(hub, "A")
    assert hub.holding_sessions() == ["B", "A"]
    hub.resume()
    join([ta, tb])


def test_disabling_link_clears_session_pauses():
    hub = RemoteHub()
    hub.pause("A")
    hub.set_link_enabled(False)
    assert not hub.is_paused and hub.paused_sessions() == set()


# ---------------------------------------------------------------- 文件夹名字段
@pytest.mark.parametrize("value,expected", [
    ("shion", "shion"),
    ("  诗音 项目  ", "诗音 项目"),
    ("a\x00b\x1fc\x7f", "abc"),
    ("evil\u202egnp.exe", "evilgnp.exe"),
    ("x" * 64, "x" * 64),
    ("x" * 65, None),
    ("\x01\x02", None),
    ("", None),
    ("a/b", None),
    ("a\\b", None),
    (123, None),
    (None, None),
    (["shion"], None),
])
def test_clean_project(value, expected):
    assert clean_project(value) == expected


def test_bad_project_is_dropped_without_rejecting_the_event():
    assert parse_meta({"session": "s1", "project": "x" * 100}) == {"session": "s1"}
    assert parse_meta({"session": "s1", "project": 5}) == {"session": "s1"}
    assert parse_meta({"session": "s1", "project": "ok"}) == {"session": "s1", "project": "ok"}
    assert parse_meta({}) == {}  # 旧格式


@pytest.fixture
def server():
    events, takes = [], []

    def take(session=None):
        takes.append(session)
        return ""

    hub = RemoteHub()
    srv = ShionServer(lambda t, d, m=None: events.append((t, d, m)), take, port=0, hub=hub)
    srv.start()
    yield srv, events, takes
    hub.resume()
    srv.stop()


def post(srv, path, payload):
    req = urllib.request.Request(f"http://127.0.0.1:{srv.port}{path}", data=json.dumps(payload).encode(),
                                 headers=auth(srv))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=5) as resp:
        return resp.status, json.loads(resp.read())


def test_http_event_with_bad_project_is_still_accepted(server):
    srv, events, _ = server
    assert post(srv, "/event", {"type": "working", "session": "s1", "project": "a\x00" * 100})[0] == 200
    assert post(srv, "/event", {"type": "working", "session": "s1", "project": "proj"})[0] == 200
    assert events[0][2] == {"session": "s1"}
    assert events[1][2] == {"session": "s1", "project": "proj"}


def test_prompt_releases_only_its_own_session(server):
    srv, _, _ = server
    srv.hub.pause("A")
    srv.hub.pause("B")
    post(srv, "/event", {"type": "prompt", "session": "A"})
    assert not srv.hub.is_session_paused("A") and srv.hub.is_session_paused("B")
    post(srv, "/event", {"type": "prompt"})  # 旧 hook 没带 session：和原来一样解除全部
    assert not srv.hub.is_paused


def test_stop_without_hold_drops_only_that_sessions_unused_pause(server):
    srv, _, _ = server
    srv.hub.pause("A")
    srv.hub.pause("B")
    post(srv, "/event", {"type": "stop", "session": "A"})
    assert not srv.hub.is_session_paused("A") and srv.hub.is_session_paused("B")


def test_feedback_take_passes_the_requesters_session(server):
    srv, _, takes = server
    post(srv, "/feedback/take", {"session": "A"})
    post(srv, "/feedback/take", {})
    post(srv, "/feedback/take", {"session": 5})  # 不合法按没带
    assert takes == ["A", None, None]


# ---------------------------------------------------------------- hook
def load_hook():
    spec = importlib.util.spec_from_file_location("shion_hook_ps", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("cwd,expected", [
    (r"D:\work\shion", "shion"),
    ("/home/u/proj/", "proj"),
    ("C:\\", ""),
    ("", ""),
    (None, ""),
    ("x" * 65, ""),
])
def test_hook_reports_only_the_folder_name(cwd, expected):
    h = load_hook()
    meta = h.session_meta("Stop", {"session_id": "s1", "cwd": cwd})
    assert meta.get("project", "") == expected
    assert all("\\" not in str(v) and "/" not in str(v) for v in meta.values())


def test_hook_sends_folder_and_takes_only_its_sessions_feedback(server, tmp_path):
    srv, events, takes = server
    stdin = json.dumps({"session_id": "s9", "cwd": r"D:\work\alpha"}).encode()
    r = run_hook("UserPromptSubmit", srv.port, tmp_path, stdin=stdin)
    assert r.returncode == 0
    assert events[0][0] == "prompt" and events[0][2]["project"] == "alpha"
    assert takes == ["s9"]


# ---------------------------------------------------------------- 存档：反馈按会话
def test_feedback_queue_is_kept_per_session_and_legacy_items_have_no_owner():
    pet = PetState(SaveData(), T0)
    pet.feedback_good(T0)  # 无归属（原行为）
    pet.feedback_good(T0, ["A", "B"])  # “全部”：各一份
    pet.feedback_bad("只给 B", T0, ["B"])
    assert [i["kind"] for i in pet.take_feedback(T0, session="A")] == ["good", "good"]  # 无归属 + A 的
    assert pet.take_feedback(T0, session="A") == []
    assert pet.take_feedback(T0, session=None) == []  # 旧请求只取无归属的（已被 A 取走）
    assert [(i["kind"], i["text"]) for i in pet.take_feedback(T0, session="B")] == [("good", ""), ("bad", "只给 B")]
    assert _feedback_items([{"kind": "good", "text": ""}]) == [{"kind": "good", "text": ""}]


def test_feedback_cap_is_per_owner():
    pet = PetState(SaveData(), T0)
    for _ in range(7):
        pet.feedback_good(T0, ["A"])
    pet.feedback_good(T0, ["B"])
    assert len(pet.take_feedback(T0, session="A")) == 5
    assert len(pet.take_feedback(T0, session="B")) == 1


# ---------------------------------------------------------------- 会话名称
def ui(key, **kw):
    return {"session_n": "会话 {n}"}[key].format(**kw)


def test_same_folder_gets_numbered_in_order_of_appearance():
    names = SessionNames()
    names.note("s1", "proj")
    names.note("s2", "other")
    names.note("s3", "proj")
    names.note("s4", "proj")
    assert names.labels(["s4", "s3", "s2", "s1"], False, ui) == {
        "s1": "proj", "s2": "other", "s3": "proj (2)", "s4": "proj (3)"}


def test_privacy_mode_and_missing_names_use_session_numbers():
    names = SessionNames()
    names.note("s1", "secret-client")
    names.note("s2")
    assert names.labels(["s1", "s2"], True, ui) == {"s1": "会话 1", "s2": "会话 2"}
    assert names.labels(["s1", "s2"], False, ui) == {"s1": "secret-client", "s2": "会话 2"}


# ---------------------------------------------------------------- 控制器与菜单
def world2():
    """两个 CC 会话：A（pid 100，工具 300）和 B（pid 110，工具 310）。"""
    created = {100: CC.created, 110: CC.created, 300: ft(START + 0.2), 310: ft(START + 0.2)}
    table = {100: (1, "claude.exe"), 110: (1, "claude.exe"), 300: (100, "cmd.exe"), 310: (110, "cmd.exe")}
    return FakeView(table, created)


def proc(pid):
    return {"pid": pid, "created": CC.created, "name": "claude.exe", "entry": "cli", "hooks": []}


def work(env, session, project, pid, tool="t"):
    env.ctl.handle_event("working", json.dumps({"tool": "bash", "target": ""}),
                         {"session": session, "tool_id": tool + session, "proc": proc(pid), "project": project})


@pytest.fixture
def two(env):  # noqa: F811
    env.world = world2()
    env.ctl.process_view = env.world.view()
    env.ctl.hook_images = ()
    work(env, "A", "alpha", 100)
    work(env, "B", "beta", 110)
    yield env
    env.ctl.hub.resume()


def remote(env):
    menu = env.ctl.build_menu()
    return menu, find_action(menu, "工作遥控").menu()


def tree(menu):
    out = []
    for a in menu.actions():
        if a.isSeparator():
            out.append("---")
        else:
            out.append((a.text(), a.isEnabled(), tree(a.menu()) if a.menu() else None))
    return out


SINGLE_IDLE = [("停下", True, None), ("立即中断", False, None), ("做得好", True, None), ("有问题……", True, None)]


def test_menu_with_no_or_one_session_is_unchanged(env):  # noqa: F811
    _, rem = remote(env)
    assert tree(rem) == SINGLE_IDLE
    env.ctl.process_view = world2().view()
    work(env, "A", "alpha", 100)
    _, rem = remote(env)
    assert tree(rem) == [("停下", True, None), ("立即中断", True, None), ("做得好", True, None),
                         ("有问题……", True, None)]
    find_action(rem, "停下").trigger()
    assert env.ctl.hub.is_global_paused  # 和原来一样：全局停下
    _, rem = remote(env)
    assert tree(rem) == [("继续", True, None), ("立即中断", True, None), ("做得好", True, None),
                         ("有问题……", True, None)]
    find_action(rem, "做得好").trigger()
    assert env.state.save.feedback_queue == [{"kind": "good", "text": ""}]  # 无归属
    env.ctl.hub.resume()


def test_two_sessions_turn_each_button_into_a_submenu(two):
    _, rem = remote(two)
    sub = [("alpha", True, None), ("beta", True, None), "---", ("全部", True, None)]
    assert tree(rem) == [("停下", True, sub), ("立即中断", True, sub), ("做得好", True, sub), ("有问题……", True, sub)]


def test_stopping_a_leaves_b_and_resume_has_one_target(two):
    _, rem = remote(two)
    find_action(find_action(rem, "停下").menu(), "alpha").trigger()
    hub = two.ctl.hub
    assert hub.is_session_paused("A") and not hub.is_session_paused("B") and not hub.is_global_paused
    assert hub.wait_gate(5, "B") == (False, False)
    _, rem = remote(two)
    entries = tree(rem)
    assert entries[0] == ("继续", True, None)  # 只有 A 停着：直接一项
    assert entries[1][0] == "停下" and entries[1][2][0] == ("alpha", False, None)  # 已停下的置灰
    find_action(rem, "继续").trigger()
    assert not hub.is_paused and not two.state.paused


def test_stop_all_then_user_prompt_releases_only_its_own_session(two):
    _, rem = remote(two)
    find_action(find_action(rem, "停下").menu(), "全部").trigger()
    hub = two.ctl.hub
    ta, ra = waiter(hub, "A")
    tb, rb = waiter(hub, "B", seconds=1.0)
    hub.resume("A")  # 服务线程收到 A 的 prompt 时做的
    two.ctl.handle_event("prompt", None, {"session": "A"})
    join([ta])
    assert ra == [(False, False)] and hub.is_session_paused("B") and two.state.paused
    join([tb])
    assert rb == [(True, False)]


def test_interrupting_a_never_touches_b_processes(two):
    _, rem = remote(two)
    find_action(find_action(rem, "立即中断").menu(), "alpha").trigger()
    assert two.world.killed == [300]
    assert two.ctl.hub.interrupt_pending("A") and not two.ctl.hub.interrupt_pending("B")
    assert two.state.working_sessions(two.now) == ["B"]


def test_interrupt_all_matches_old_behaviour(two):
    _, rem = remote(two)
    find_action(find_action(rem, "立即中断").menu(), "全部").trigger()
    assert sorted(two.world.killed) == [300, 310]


def world_shared():
    """A、B 共用一个宿主进程 pid 100（工具 300、301 都是它的子进程）；C 自己的进程 pid 110（工具 310）。"""
    created = {100: CC.created, 110: CC.created,
               300: ft(START + 0.2), 301: ft(START + 0.2), 310: ft(START + 0.2)}
    table = {100: (1, "claude.exe"), 110: (1, "claude.exe"),
             300: (100, "cmd.exe"), 301: (100, "cmd.exe"), 310: (110, "cmd.exe")}
    return FakeView(table, created)


@pytest.fixture
def shared(env):  # noqa: F811
    env.world = world_shared()
    env.ctl.process_view = env.world.view()
    env.ctl.hook_images = ()
    work(env, "A", "alpha", 100)
    work(env, "B", "beta", 100)
    yield env
    env.ctl.hub.resume()


def test_interrupting_a_session_that_shares_its_process_only_stops_it(shared):
    """共用进程时按进程结束会把 B 的工具也杀掉：改为只让 A 停下。"""
    _, rem = remote(shared)
    find_action(find_action(rem, "立即中断").menu(), "alpha").trigger()
    hub = shared.ctl.hub
    assert shared.world.killed == []
    assert hub.is_session_paused("A") and not hub.is_session_paused("B")
    assert not hub.interrupt_pending("A") and not hub.interrupt_pending("B")
    assert sorted(shared.state.working_sessions(shared.now)) == ["A", "B"]


def test_interrupting_every_session_on_a_shared_process_still_kills(shared):
    _, rem = remote(shared)
    find_action(find_action(rem, "立即中断").menu(), "全部").trigger()
    assert sorted(shared.world.killed) == [300, 301]


def test_partial_interrupt_kills_own_process_and_stops_the_shared_one(shared):
    work(shared, "C", "gamma", 110)
    shared.ctl.interrupt_work(only=["A", "C"])
    hub = shared.ctl.hub
    assert shared.world.killed == [310]  # 只有 C 自己的工具
    assert hub.interrupt_pending("C") and not hub.interrupt_pending("A")
    assert hub.is_session_paused("A") and not hub.is_session_paused("B")
    assert sorted(shared.state.working_sessions(shared.now)) == ["A", "B"]


def test_feedback_goes_only_to_the_chosen_session(two):
    _, rem = remote(two)
    find_action(find_action(rem, "做得好").menu(), "beta").trigger()
    assert two.ctl.take_feedback_text("A") == ""
    assert two.ctl.take_feedback_text(None) == ""
    assert two.ctl.take_feedback_text("B") == PRAISE


def test_feedback_all_gives_each_session_one_copy_but_counts_once(two):
    before = two.state.save.affection
    temp_said = len(two.said)
    _, rem = remote(two)
    find_action(find_action(rem, "做得好").menu(), "全部").trigger()
    assert two.state.save.affection - before == two.state.config.praise_affection
    assert len(two.said) - temp_said <= 1
    assert two.ctl.take_feedback_text("A") == PRAISE
    assert two.ctl.take_feedback_text("B") == PRAISE


def test_bad_feedback_asks_for_session_then_opens_the_input(two):
    _, rem = remote(two)
    find_action(find_action(rem, "有问题……").menu(), "alpha").trigger()
    panel = two.ctl._input_panel
    assert panel is not None and panel.isVisible()
    panel.submitted.emit("这里不对")
    assert two.ctl.take_feedback_text("B") == ""
    assert "这里不对" in two.ctl.take_feedback_text("A")
    panel.hide()


def test_privacy_mode_numbers_the_sessions(two):
    two.ctl.set_privacy(True)
    _, rem = remote(two)
    labels = [a.text() for a in find_action(rem, "停下").menu().actions() if not a.isSeparator()]
    assert labels == ["会话 1", "会话 2", "全部"]


def test_same_folder_sessions_get_numbered_in_menu(env):  # noqa: F811
    env.ctl.process_view = world2().view()
    work(env, "A", "proj", 100)
    work(env, "B", "proj", 110)
    _, rem = remote(env)
    labels = [a.text() for a in find_action(rem, "做得好").menu().actions() if not a.isSeparator()]
    assert labels == ["proj", "proj (2)", "全部"]


def test_pause_timeout_of_a_single_paused_session_ends_only_it(two):
    hub = two.ctl.hub
    two.ctl.stop_work("A")
    two.ctl.stop_work("B")
    tb, rb = waiter(hub, "B", seconds=1.0)
    two.ctl.handle_event("pause_timeout", None, {"session": "A"})
    assert hub.is_session_paused("B")
    join([tb])
    assert rb == [(True, False)]


# ---------------------------------------------------------------- 检查点面板
def held_both(two):
    hub = two.ctl.hub
    two.ctl.stop_work("A")
    two.ctl.stop_work("B")
    ta, ra = waiter(hub, "A")
    tb, rb = waiter(hub, "B")
    two.win.show()
    two.advance(0.1)
    return (ta, ra), (tb, rb)


def test_panel_lists_each_held_session_and_hides_the_single_badge(two):
    (ta, ra), (tb, rb) = held_both(two)
    panel = two.ctl._checkpoint
    assert panel is not None and panel.wanted and panel.isVisible()
    assert [name for _, name in panel.rows] == ["alpha", "beta"]
    assert not two.win.paused_badge_shown
    assert panel.focusPolicy() == Qt.NoFocus and panel.testAttribute(Qt.WA_ShowWithoutActivating)
    assert panel.windowFlags() & Qt.WindowDoesNotAcceptFocus
    two.ctl.resume_work()
    join([ta, tb])


def test_panel_buttons_are_mouse_only_and_armed_after_delay(two):
    (ta, ra), (tb, rb) = held_both(two)
    panel = two.ctl._checkpoint
    resume_a, _ = panel.buttons["A"]
    QTest.mouseClick(resume_a, Qt.LeftButton)  # 0.6 秒内：无效
    assert two.ctl.hub.is_session_paused("A")
    two.advance(0.7)
    resume_a, _ = panel.buttons["A"]
    QTest.keyClick(resume_a, Qt.Key_Space)  # 键盘：无效
    assert two.ctl.hub.is_session_paused("A")
    _, end_b = panel.buttons["B"]
    QTest.mouseClick(end_b, Qt.LeftButton)
    join([tb])
    assert rb == [(False, True)]  # 只结束 B 正在等的 hook
    assert ta.is_alive() and two.ctl.hub.is_session_paused("A")
    assert not panel.wanted and two.win.paused_badge_shown  # 只剩 A：换回单个标签
    two.win.resume_requested.emit()
    join([ta])
    assert ra == [(False, False)]


def test_panel_resume_releases_only_that_session(two):
    (ta, ra), (tb, rb) = held_both(two)
    two.advance(0.7)
    resume_a, _ = two.ctl._checkpoint.buttons["A"]
    QTest.mouseClick(resume_a, Qt.LeftButton)
    join([ta])
    assert ra == [(False, False)] and two.ctl.hub.is_session_paused("B") and tb.is_alive()
    two.ctl.resume_work()
    join([tb])


def test_single_held_session_shows_badge_with_project_name(two):
    hub = two.ctl.hub
    two.ctl.stop_work("A")
    t, _ = waiter(hub, "A")
    two.win.show()
    two.advance(0.1)
    assert two.win.paused_badge_shown and two.win._pause_badge.text == "暂停中：alpha"
    assert two.ctl._checkpoint is None or not two.ctl._checkpoint.wanted
    two.win.resume_requested.emit()  # 点标签：只放行 A
    join([t])
    assert not hub.is_paused


def test_single_held_badge_hides_the_name_in_privacy_mode(two):
    two.ctl.set_privacy(True)
    two.ctl.stop_work("A")
    t, _ = waiter(two.ctl.hub, "A")
    two.win.show()
    two.advance(0.1)
    assert two.win._pause_badge.text == "暂停中"
    two.ctl.resume_work()
    join([t])
