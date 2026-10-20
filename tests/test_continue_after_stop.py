"""这一轮被诗音结束后（立即中断 / 停太久）的“继续”：终端版替用户发送，桌面端复制到剪贴板。"""
import json
import os
import subprocess
import sys

import pytest
from PySide6.QtGui import QGuiApplication

from shion import console_send, interrupt
from shion.console_send import check_screen
from tests.test_controller import T0, env, qapp, find_action  # noqa: F401
from tests.test_interrupt import CC, HOOK_IMAGES, fake_world

RULE = "─" * 80


def screen(prompt=">", above=(), below=("  ? for shortcuts",), filler=10):
    return [""] * filler + list(above) + [RULE, prompt, RULE] + list(below)


# ---------------------------------------------------------------- 读屏判断
def test_empty_input_box_can_send():
    assert check_screen(screen(">")) is None
    assert check_screen(screen("❯\xa0")) is None


def test_reply_with_plain_numbered_list_still_counts_as_empty_input():
    reply = ["● Could you say what you'd like to do?", "  1. What you were working on", "  2. Where you left off"]
    assert check_screen(screen(">", above=reply)) is None


def test_draft_is_not_overwritten():
    assert check_screen(screen("> DRAFT-abc"), cursor=(11, 11)) == "draft"
    multi = [""] * 5 + [RULE, "> first line", "  second line", RULE]
    assert check_screen(multi) == "draft"


def test_placeholder_counts_as_empty_only_with_cursor_right_after_prompt():
    s = screen('>\xa0Try "write a test for <filepath>"')
    row = s.index('>\xa0Try "write a test for <filepath>"')
    assert check_screen(s, cursor=(2, row)) is None
    assert check_screen(s, cursor=(20, row)) == "draft"  # 光标不在提示符后面：可能是用户打的字
    assert check_screen(s) == "draft"  # 不知道光标位置：保守
    assert check_screen(screen('> Try "x" and more'), cursor=(2, 11)) == "draft"


@pytest.mark.parametrize("dialog", [
    [" Do you want to proceed?", " > 1. Yes", "   2. Yes, and always allow access", "   3. No", " Esc to cancel"],
    [" Quick safety check: Is this a project you created or one you trust?", " > No, exit",
     "   Yes, I trust this folder", " Enter to confirm · Esc to cancel"],
    [" Pick one", " ❯ 1. Option A", "   2. Option B"],
])
def test_confirmation_dialog_blocks_sending(dialog):
    assert check_screen([""] * 10 + [RULE] + dialog) == "dialog"
    assert check_screen(screen(">", above=dialog)) == "dialog"  # 有输入框也不冒险


def test_no_input_box_means_no_send():
    assert check_screen(["● working…", "esc to interrupt"]) == "no_input"
    assert check_screen([]) == "no_input"


def test_process_must_match_the_hook_report():
    table = {10: (1, "claude.exe"), 11: (1, "node.exe")}
    assert console_send.check_process(10, 5, table, lambda pid: 5)
    assert not console_send.check_process(10, 6, table, lambda pid: 5)  # PID 被复用
    assert not console_send.check_process(11, 5, table, lambda pid: 5)  # 不是 claude.exe
    assert not console_send.check_process(12, 5, table, lambda pid: 5)  # 已退出


def test_cli_refuses_a_process_that_is_not_claude():
    """子进程命令行：拿本进程（python）当目标，必须在附着之前就拒绝。"""
    if os.name != "nt":
        pytest.skip("Windows")
    from shion import winproc
    me = os.getpid()
    r = subprocess.run([sys.executable, "-m", "shion.console_send", "--pid", str(me),
                        "--created", str(winproc.process_created(me)), "--text", "继续"],
                       capture_output=True, timeout=30, cwd=str(console_send.__file__).rsplit("shion", 1)[0])
    assert json.loads(r.stdout) == {"ok": False, "reason": "gone"} and r.returncode == 1


def test_is_terminal():
    assert interrupt.is_terminal(interrupt.CCProcess(1, 2, "claude.exe", "cli"))
    assert not interrupt.is_terminal(interrupt.CCProcess(1, 2, "claude.exe", "claude-desktop"))
    assert not interrupt.is_terminal(interrupt.CCProcess(1, 2, "node.exe", "cli"))
    assert not interrupt.is_terminal(None)


# ---------------------------------------------------------------- 控制器
TERMINAL = {"pid": CC.pid, "created": CC.created, "name": "claude.exe", "entry": "cli", "hooks": CC.hooks}
DESKTOP = {**TERMINAL, "entry": "claude-desktop"}


@pytest.fixture
def pet(env):  # noqa: F811
    world = fake_world()
    env.ctl.process_view = world.view()
    env.ctl.hook_images = HOOK_IMAGES
    env.sent = []
    env.reply = {"ok": True}
    env.ctl.continue_runner = lambda proc, text, done: (env.sent.append((proc.pid, text)), done(env.reply))
    yield env
    env.ctl.hub.resume()


def work(env, proc, session="s1"):
    env.ctl.handle_event("working", json.dumps({"tool": "bash", "target": ""}),
                         {"session": session, "tool_id": "t1", "proc": proc})


def remote_texts(env):
    menu = env.ctl.build_menu()
    remote = find_action(menu, "工作遥控").menu()
    return menu, remote, [a.text() for a in remote.actions()]


def interrupt_and_stop(env, proc, session="s1"):
    work(env, proc, session)
    env.ctl.interrupt_work()
    env.ctl.handle_event("work_stopped", None, {"session": session})


def test_menu_unchanged_before_anything_ended(pet):
    _, _, texts = remote_texts(pet)
    assert texts == ["停下", "立即中断", "做得好", "有问题……"]


def test_terminal_interrupt_offers_send_continue(pet):
    interrupt_and_stop(pet, TERMINAL)
    menu, remote, texts = remote_texts(pet)
    assert texts == ["继续（发送“继续”）", "停下", "立即中断", "做得好", "有问题……"]
    find_action(remote, "继续（发送“继续”）").trigger()
    assert pet.sent == [(CC.pid, "继续")]
    assert pet.said[-1] == "发过去啦，接着干～"
    assert remote_texts(pet)[2][0] == "停下"  # 发过了，菜单恢复


@pytest.mark.parametrize("reason, line, keep", [
    ("draft", "输入框里还有没发出去的字，我就不动啦", True),
    ("dialog", "屏幕上像是有确认框，我不替你按回车哦", True),
    ("no_input", "没找到那个终端，去 CC 里说一声吧", True),
    ("gone", "没找到那个终端，去 CC 里说一声吧", False),
    ("error", "没找到那个终端，去 CC 里说一声吧", True),
])
def test_refused_send_explains_why(pet, reason, line, keep):
    interrupt_and_stop(pet, TERMINAL)
    pet.reply = {"ok": False, "reason": reason}
    pet.ctl.continue_ended()
    assert pet.said[-1] == line
    assert (remote_texts(pet)[2][0] == "继续（发送“继续”）") is keep  # 没发出去可以再试


def test_only_one_send_at_a_time(pet):
    interrupt_and_stop(pet, TERMINAL)
    pending = []
    pet.ctl.continue_runner = lambda proc, text, done: pending.append(done)
    pet.ctl.continue_ended()
    pet.ctl.continue_ended()
    assert len(pending) == 1
    menu, remote, _ = remote_texts(pet)
    assert not find_action(remote, "继续（发送“继续”）").isEnabled()
    pending[0]({"ok": True})
    assert pet.said[-1] == "发过去啦，接着干～"


def test_desktop_interrupt_copies_continue(pet):
    interrupt_and_stop(pet, DESKTOP)
    menu, remote, texts = remote_texts(pet)
    assert texts == ["继续", "停下", "立即中断", "做得好", "有问题……"]
    QGuiApplication.clipboard().setText("")
    find_action(remote, "继续").trigger()
    assert QGuiApplication.clipboard().text() == "继续"
    assert pet.said[-1] == "已经复制好啦，去 CC 里粘贴发送就行～"
    assert pet.sent == []  # 桌面端不注入
    assert remote_texts(pet)[2][0] == "停下"


def test_desktop_interrupt_itself_is_unchanged(pet):
    work(pet, DESKTOP)
    pet.ctl.interrupt_work()
    assert pet.said[-1] == "已经中断啦，在 CC 里说一声就能继续"
    assert remote_texts(pet)[2] == ["停下", "立即中断", "做得好", "有问题……"]  # 还没真的结束


def test_pause_timeout_offers_continue(pet):
    work(pet, DESKTOP)
    pet.ctl.stop_work()
    pet.ctl.handle_event("pause_timeout", None, {"session": "s1"})
    assert remote_texts(pet)[2][0] == "继续"
    pet.ctl.continue_ended()
    assert QGuiApplication.clipboard().text() == "继续"


def test_terminal_pause_timeout_offers_send(pet):
    work(pet, TERMINAL)
    pet.ctl.stop_work()
    pet.ctl.handle_event("pause_timeout", None, {"session": "s1"})
    assert remote_texts(pet)[2][0] == "继续（发送“继续”）"


def test_interrupt_while_writing_then_stop_offers_continue(pet):
    """中断时正在写字（没碰到检查点），这一轮自己结束：同样可以继续。"""
    work(pet, TERMINAL)
    pet.ctl.interrupt_work()
    pet.ctl.handle_event("stop", None, {"session": "s1"})
    assert remote_texts(pet)[2][0] == "继续（发送“继续”）"


def test_unknown_process_falls_back_to_copy(pet):
    pet.ctl.handle_event("working", None, {"session": "s1", "tool_id": "t1"})
    pet.ctl.stop_work()
    pet.ctl.handle_event("pause_timeout", None, {"session": "s1"})
    assert remote_texts(pet)[2][0] == "继续"


@pytest.mark.parametrize("etype", ["prompt", "working"])
def test_user_continuing_in_cc_clears_the_offer(pet, etype):
    interrupt_and_stop(pet, TERMINAL)
    pet.ctl.handle_event(etype, None, {"session": "s1", "tool_id": "t2", "proc": TERMINAL})
    assert remote_texts(pet)[2][0] == "停下"


def test_other_session_activity_keeps_the_offer(pet):
    interrupt_and_stop(pet, TERMINAL)
    pet.ctl.handle_event("prompt", None, {"session": "s2", "proc": TERMINAL})
    assert remote_texts(pet)[2][0] == "继续（发送“继续”）"


def test_paused_menu_keeps_plain_resume(pet):
    interrupt_and_stop(pet, TERMINAL)
    work(pet, TERMINAL, "s2")
    pet.ctl.stop_work()
    assert remote_texts(pet)[2][0] == "继续"
    assert "继续（发送“继续”）" not in remote_texts(pet)[2]


@pytest.mark.parametrize("lang, text, menu_label", [
    ("en", "Continue", "Continue (send “Continue”)"),
    ("ja", "続けて", "続ける（「続けて」を送信）"),
])
def test_message_follows_language(pet, lang, text, menu_label):
    pet.ctl.set_language(lang)
    interrupt_and_stop(pet, TERMINAL)
    menu = pet.ctl.build_menu()
    remote = menu.actions()[1].menu()
    assert remote.actions()[0].text() == menu_label
    pet.ctl.continue_ended()
    assert pet.sent[-1][1] == text
    assert "claude" not in pet.said[-1].lower()


def test_new_lines_have_no_claude():
    from shion.lines import Lines
    for lang in ("zh", "en", "ja"):
        lines = Lines()
        lines.set_language(lang)
        for key in ("continue_text", "menu_continue_send", "continue_sent", "continue_copied",
                    "continue_draft", "continue_dialog", "continue_failed"):
            assert lines.ui(key) and "claude" not in lines.ui(key).lower()
