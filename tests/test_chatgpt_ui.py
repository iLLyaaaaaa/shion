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
