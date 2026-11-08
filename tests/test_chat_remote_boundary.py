"""Claude 聊天只读观察与 Claude Code 遥控的边界。"""
import pytest

from tests.test_controller import env, find_action, qapp  # noqa: F401


def chat(env, phase="working"):
    env.ctl.handle_event("chat_event", "sample task", {"event": phase, "client": "desktop"})


@pytest.mark.parametrize("lang", ["zh", "en", "ja"])
@pytest.mark.parametrize("phase", ["working", "need_input", "done"])
def test_chat_only_disables_entire_remote_and_never_sets_pause(env, lang, phase):
    ctl = env.ctl
    ctl.set_language(lang)
    chat(env)
    if phase != "working":
        chat(env, phase)
    menu = ctl.build_menu()
    action = find_action(menu, ctl.lines.ui("menu_remote"))
    hint = ctl.lines.ui("remote_cc_only_hint")
    assert "Claude" in hint and hint != "remote_cc_only_hint"
    assert not action.isEnabled() and action.toolTip() == hint
    assert all(not a.isEnabled() and a.toolTip() == hint for a in action.menu().actions())
    assert ctl.remote_sessions() == [] and not ctl.can_interrupt()
    assert ctl.hub.permissions.pending() == [] and ctl._perm_panel is None

    # 旧菜单回调或直接调用也不能为只读来源产生暂停/中断标记。
    ctl.stop_work()
    ctl.stop_work("desktop")
    ctl.stop_all(["desktop"])
    ctl.interrupt_work()
    ctl.resume_work()
    assert not ctl.hub.is_paused and not env.state.paused
    assert not ctl.hub.interrupt_pending("desktop") and not env.win.paused_badge_shown
    assert ctl.chat_activity.phase == ("idle" if phase == "done" else phase)
    if phase == "working":
        assert env.win.sprite_name == "working"


@pytest.mark.parametrize("lang", ["zh", "en", "ja"])
@pytest.mark.parametrize("v2", [False, True])
@pytest.mark.parametrize("private,muted", [(False, False), (True, True)])
def test_pause_only_holds_cc_and_keeps_parallel_chat_working(env, lang, v2, private, muted):
    ctl = env.ctl
    ctl.set_language(lang)
    ctl.set_v2_scheduler_enabled(v2)
    env.data.privacy_mode = private
    ctl.set_muted(muted)
    ctl.handle_event("prompt", meta={"session": "cc", "project": "project"})
    chat(env)
    env.said.clear()
    assert ctl.remote_sessions() == ["cc"]
    menu = ctl.build_menu()
    remote = find_action(menu, ctl.lines.ui("menu_remote"))
    assert remote.isEnabled()
    find_action(remote.menu(), ctl.lines.ui("menu_stop")).trigger()
    assert ctl.hub.is_session_paused("cc") and env.state.paused
    assert ctl.chat_activity.phase == "working" and env.state.observed_working
    assert env.win.sprite_name == "working"
    if muted:
        assert env.said == []
    else:
        assert ctl.lines.ui("pause_cc_only") in env.said[-1]

    assert ctl.hub.wait_gate(0, "cc") == (True, False)
    ctl._sync_pause()
    ctl.sync()
    assert ctl.hub.holding_sessions() == ["cc"]
    assert env.win.paused_badge_shown and "Claude Code" in env.win._pause_badge.text
    assert env.win.sprite_name == "working" and ctl.chat_activity.phase == "working"
    if not muted:
        assert ctl.lines.ui("pause_cc_only") in env.said[-1]
    ctl.resume_work()
    assert not ctl.hub.is_paused and not env.win.paused_badge_shown
    assert env.win.sprite_name == "working" and ctl.chat_activity.phase == "working"


def test_chat_started_after_cc_pause_never_inherits_pause_display(env):
    ctl = env.ctl
    ctl.handle_event("prompt", meta={"session": "cc"})
    ctl.stop_work()
    assert env.win.sprite_name == "stop"
    chat(env)
    assert env.win.sprite_name == "working" and ctl.chat_activity.phase == "working"
    assert ctl.hub.is_session_paused("cc")
    chat(env, "need_input")
    assert ctl.chat_activity.phase == "need_input" and not ctl.hub.permissions.pending()
    chat(env, "done")
    assert ctl.chat_activity.phase == "idle" and ctl.hub.is_session_paused("cc")


def test_old_pause_without_cc_is_cleared_before_later_checkpoint(env):
    chat(env)
    env.ctl.hub.pause()
    env.state.paused = True
    env.advance(0.1)
    assert not env.ctl.hub.is_paused and not env.state.paused
    assert env.ctl.hub.wait_gate(0, "later-cc") == (False, False)
    assert env.win.sprite_name == "working" and not env.win.paused_badge_shown


def test_stale_menu_and_all_targets_cannot_pause_after_cc_ends(env):
    ctl = env.ctl
    ctl.handle_event("prompt", meta={"session": "cc"})
    menu = ctl.build_menu()
    old_stop = find_action(find_action(menu, ctl.lines.ui("menu_remote")).menu(), ctl.lines.ui("menu_stop"))
    ctl.handle_event("stop", meta={"session": "cc"})
    chat(env)
    old_stop.trigger()
    ctl.stop_all(["cc"])
    assert not ctl.hub.is_paused and not env.state.paused


def test_stale_session_cannot_be_paused_while_another_cc_is_active(env):
    ctl = env.ctl
    ctl.handle_event("prompt", meta={"session": "cc"})
    chat(env)
    ctl.stop_work("desktop")
    ctl.stop_all(["desktop"])
    assert not ctl.hub.is_paused


def test_pending_cc_permission_is_active_even_without_working_event(env):
    chat(env)
    ctl = env.ctl
    request = ctl.hub.permissions.open("Read", "sample", session="cc")
    ctl._sync_permission()
    menu = ctl.build_menu()
    assert find_action(menu, ctl.lines.ui("menu_remote")).isEnabled()
    assert ctl.remote_sessions() == ["cc"]
    ctl._on_permission_decided(request, False)
    assert ctl.hub.permissions.wait(request, 0) == "deny"
    assert ctl.chat_activity.phase == "working" and env.state.observed_working


def test_parallel_chat_is_excluded_from_per_session_and_all_checkpoint_controls(env):
    ctl = env.ctl
    for session in ("cc-a", "cc-b"):
        ctl.handle_event("prompt", meta={"session": session})
    chat(env)
    menu = ctl.build_menu()
    remote = find_action(menu, ctl.lines.ui("menu_remote")).menu()
    pause = find_action(remote, ctl.lines.ui("menu_stop")).menu()
    pause.actions()[0].trigger()
    assert ctl.hub.is_session_paused("cc-a") and not ctl.hub.is_session_paused("cc-b")
    assert ctl.hub.wait_gate(0, "cc-b") == (False, False)
    assert env.win.sprite_name == "working" and ctl.chat_activity.phase == "working"
    ctl.resume_work()

    ctl.stop_all(["cc-a", "cc-b", "desktop"])
    assert ctl.hub.paused_sessions() == {"cc-a", "cc-b"}
    for session in ("cc-a", "cc-b"):
        assert ctl.hub.wait_gate(0, session) == (True, False)
    ctl._sync_pause()
    ctl.sync()
    assert [s for s, _ in ctl._checkpoint.rows] == ["cc-a", "cc-b"]
    assert "Claude Code" in ctl._checkpoint._title.text()
    assert env.win.sprite_name == "working" and ctl.chat_activity.phase == "working"
    ctl.resume_work("cc-a")
    assert ctl.hub.is_session_paused("cc-b")
    assert env.win.sprite_name == "working"
    ctl.resume_work("cc-b")
    assert not ctl.hub.is_paused and ctl.chat_activity.phase == "working"
    assert ctl.hub.wait_gate(0, "later-cc") == (False, False)


def test_legacy_cc_without_session_still_controls_cc_alongside_chat(env):
    env.ctl.handle_event("prompt")
    chat(env)
    menu = env.ctl.build_menu()
    remote = find_action(menu, env.ctl.lines.ui("menu_remote"))
    assert remote.isEnabled()
    find_action(remote.menu(), env.ctl.lines.ui("menu_stop")).trigger()
    assert env.ctl.hub.wait_gate(0) == (True, False)
    assert env.win.sprite_name == "working" and env.ctl.chat_activity.phase == "working"
    env.ctl.resume_work()
