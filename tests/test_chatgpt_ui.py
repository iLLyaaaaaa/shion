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
    before = env.data.stats["claude_tasks"], env.data.affection
    send("Stop")
    send("Stop")
    assert before == (env.data.stats["claude_tasks"], env.data.affection)
    assert not env.state.observed_working


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
        chat = next(a.menu() for a in menu.actions() if a.text() == ctl.lines.ui("chatgpt_manage"))
        assert len(chat.actions()) == 4
        assert "ChatGPT" in ctl.status_text()
        assert not home.exists()
