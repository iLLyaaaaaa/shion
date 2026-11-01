import pytest

from shion.chatgpt import ChatGPTConnection
from shion.events import parse_observation
from tests.test_controller import env, qapp


def test_chatgpt_activity_cannot_enter_claude_controls_or_rewards(env, tmp_path):
    ctl = env.ctl
    ctl.chatgpt = ChatGPTConnection(tmp_path / "data", tmp_path / "codex")
    ledger = ctl.chatgpt.ledger
    def send(kind, session="chat"):
        ledger.accept(parse_observation({"event": kind, "session_id": session, "turn_id": "1"}))
        ctl.tick()
    send("UserPromptSubmit")
    assert env.state.observed_working
    assert env.state.working_sessions(env.now) == []
    assert not ctl.can_interrupt()
    assert env.win.sprite_name == "working"
    send("PermissionRequest")
    assert env.win.sprite_name == "working"
    assert env.state.observed_working
    assert ctl.lines.ui("chatgpt_permission_unknown") in ctl.chatgpt.status(ctl.lines.ui)
    before = env.data.stats["claude_tasks"], env.data.affection
    send("Stop")
    send("Stop")
    assert before == (env.data.stats["claude_tasks"], env.data.affection)
    assert not env.state.observed_working
    assert ctl.lines.ui("chatgpt_permission_unknown") not in ctl.chatgpt.status(ctl.lines.ui)


def test_claude_and_chatgpt_finish_independently(env, tmp_path):
    ctl = env.ctl
    ctl.chatgpt = ChatGPTConnection(tmp_path / "data", tmp_path / "codex")
    ctl.chatgpt.ledger.accept(parse_observation({"event": "PreToolUse", "session_id": "s", "turn_id": "t"}))
    ctl.handle_event("prompt", None, {"session": "claude"})
    ctl.tick()
    assert env.state.is_working(env.now) and env.state.observed_working
    ctl.chatgpt.ledger.accept(parse_observation({"event": "Stop", "session_id": "s", "turn_id": "t"}))
    ctl.tick()
    assert env.state.is_working(env.now) and not env.state.observed_working
    ctl.toggle_chatgpt()
    assert env.state.working_sessions(env.now) == ["claude"]
    assert not ctl.chatgpt.enabled


def test_localized_management_menu_does_not_write_config(env, tmp_path):
    ctl = env.ctl
    home = tmp_path / "codex"
    ctl.chatgpt = ChatGPTConnection(tmp_path / "data", home)
    for lang in ("zh", "en", "ja"):
        ctl.set_language(lang)
        menu = ctl.build_menu()
        ai = next(a.menu() for a in menu.actions() if a.text() == ctl.lines.ui("menu_ai"))
        chat = next(a.menu() for a in ai.actions() if a.text() == ctl.lines.ui("menu_chatgpt"))
        assert [a.text() for a in chat.actions()][-3:] == [ctl.lines.ui(k) for k in ("link_manage", "link_disable", "link_remove")]
        assert len(chat.actions()) == 2 + 1 + 3  # 连接行、活动行、分隔线 + 查看配置/启停/移除
        assert not {ctl.lines.ui(k) for k in ("menu_stop", "menu_interrupt", "menu_resume", "menu_good", "menu_bad")} & {
            a.text() for a in chat.actions()}
        assert "ChatGPT" in ctl.status_text()
        assert not home.exists()


def test_lease_loss_is_neutral_and_does_not_stop_claude(env, tmp_path, monkeypatch):
    from shion.tasks import TaskLedger
    ctl = env.ctl
    ctl.chatgpt = ChatGPTConnection(tmp_path / "data", tmp_path / "codex")
    now = [0.0]
    ctl.chatgpt.ledger = TaskLedger(clock=lambda: now[0])
    notices = []
    monkeypatch.setattr(ctl, "say", lambda text, **kw: notices.append(text))
    ctl.handle_event("prompt", None, {"session": "claude"})
    ctl.chatgpt.ledger.accept(parse_observation(dict(event="PreToolUse", session_id="s", turn_id="t",
                                                   observer="isolated", leased=True)))
    ctl.tick()
    before = env.data.stats["claude_tasks"], env.data.affection
    now[0] = 10.0
    ctl.tick()
    assert not env.state.observed_working and env.state.working_sessions(env.now) == ["claude"]
    assert before == (env.data.stats["claude_tasks"], env.data.affection)
    assert ctl.lines.ui("chatgpt_disconnected") in ctl.chatgpt.status(ctl.lines.ui)  # 菜单仍是简洁状态
    assert ctl.lines.ui("chatgpt_disconnected_say") in notices  # 气泡是诗音的话
    assert ctl.lines.ui("chatgpt_disconnected") not in notices
    assert ctl.lines.ui("chatgpt_ended") not in notices
    count = len(notices)
    ctl.tick()
    assert len(notices) == count


@pytest.mark.parametrize("lang", ["zh", "en", "ja"])
def test_chatgpt_speech_lines_are_shion_voice_without_claude(lang):
    import json
    from shion.lines import LINES_DIR
    ui = json.loads((LINES_DIR / f"{lang}.json").read_text(encoding="utf-8"))["ui"]
    speech = ("chatgpt_ended", "chatgpt_interrupted", "chatgpt_disconnected_say", "v2_chatgpt_permission")
    for key in speech:
        assert ui[key] and "ChatGPT" in ui[key] and "Claude" not in ui[key]
    # 菜单状态行和气泡分开：失联的菜单文字不是气泡台词
    assert ui["chatgpt_disconnected"] != ui["chatgpt_disconnected_say"]


# ---------------------------------------------------------------- 状态能自己恢复（默认配置，不开调度器）
class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def ui(key, **kwargs):
    return key


def connection(tmp_path):
    from shion.tasks import TaskLedger
    clock = Clock()
    conn = ChatGPTConnection(tmp_path / "data", tmp_path / "codex")
    conn.ledger = TaskLedger(clock=clock)
    conn._started_at = clock()
    return conn, clock


def shown(conn):
    return conn.status(ui).splitlines()[-1], conn.activity(ui)[1]


def test_unobserved_start_is_shown_only_for_the_first_ttl(tmp_path):
    conn, clock = connection(tmp_path)
    assert shown(conn) == ("chatgpt_uncertain", "link_unknown_hint")
    clock.now += conn.ledger.ttl - 1
    assert shown(conn)[0] == "chatgpt_uncertain"
    clock.now += 2
    assert shown(conn) == ("chatgpt_observation", None)


def test_global_uncertainty_is_shown_for_a_while_then_recovers(tmp_path):
    from shion.chatgpt import UNKNOWN_WINDOW
    conn, clock = connection(tmp_path)
    clock.now += conn.ledger.ttl + 1  # 启动期已过
    conn.ledger.accept(parse_observation({"event": "Stop", "session_id": "s"}))  # 缺 turn_id
    assert conn.ledger.uncertain  # 调度器看到的仍是原来的粘滞标志
    assert shown(conn) == ("chatgpt_uncertain", "link_unknown_hint")
    clock.now += UNKNOWN_WINDOW + 1
    assert shown(conn) == ("chatgpt_observation", None)
    assert conn.ledger.uncertain  # 只改显示，不改调度器语义


def test_disconnected_tasks_are_shown_for_a_while_then_recover(tmp_path):
    from shion.chatgpt import UNKNOWN_WINDOW
    conn, clock = connection(tmp_path)
    clock.now += conn.ledger.ttl + 1
    conn.ledger.accept(parse_observation({"event": "UserPromptSubmit", "session_id": "s", "turn_id": "t"}))
    conn.ledger.disconnect(provider="chatgpt")
    assert shown(conn) == ("chatgpt_disconnected", "link_lost_hint")
    clock.now += UNKNOWN_WINDOW + 1
    assert shown(conn) == ("chatgpt_observation", None)
    assert conn.working == 0  # 断开的任务不会被算成还在工作，也不算成功


def test_toggling_twice_does_not_leave_the_status_stuck(tmp_path):
    from shion.chatgpt import UNKNOWN_WINDOW
    conn, clock = connection(tmp_path)
    clock.now += conn.ledger.ttl + 1
    conn.toggle()
    conn.toggle()
    assert conn.enabled
    assert shown(conn)[0] == "chatgpt_uncertain"
    clock.now += UNKNOWN_WINDOW + 1
    assert shown(conn) == ("chatgpt_observation", None)


def test_one_degradation_disconnects_once_and_later_tasks_are_unaffected(tmp_path):
    from types import SimpleNamespace
    from shion.observer import ObservationInbox
    conn, clock = connection(tmp_path)
    clock.now += conn.ledger.ttl + 1
    conn.server = SimpleNamespace(inbox=ObservationInbox("a" * 64))
    conn.ledger.accept(parse_observation({"event": "UserPromptSubmit", "session_id": "old", "turn_id": "t"}))
    old_key = next(iter(conn.ledger.tasks))
    conn.server.inbox.degraded.set()
    conn.poll()
    assert not conn.server.inbox.degraded.is_set()
    assert conn.ledger.tasks[old_key].state == "disconnected"
    conn.ledger.accept(parse_observation({"event": "UserPromptSubmit", "session_id": "new", "turn_id": "t"}))
    conn.poll()  # 降级已经算过一次：新任务不会被再次标成断开
    assert conn.working == 1
