from dataclasses import replace
import subprocess
import sys

import pytest

from shion.chat_activity import ChatActivity
from shion.events import Observation
from shion.sessions import SessionNames
from shion.task_board import BoardInputs, TaskBoard
from shion.tasks import TaskLedger


CC = ("claude_code", "cc")
CHATGPT = ("chatgpt", "codex-local", "codex")
CHAT = ("claude_chat",)


def ui(key, **values):
    return {
        "session_n": "会话 {n}",
        "task_board_source_claude_code": "Claude Code",
        "task_board_source_claude_chat": "Claude 聊天",
        "task_board_source_chatgpt": "ChatGPT",
        "task_board_state_plan_ready": "计划待确认",
        "task_board_tooltip": "{source} · {name} · {state} · {seconds}s",
    }.get(key, key).format(**values)


def snapshot(board, inputs=None, *, now=0, names=None, **kwargs):
    return board.snapshot(inputs or BoardInputs(**kwargs), now=now,
                          session_names=names or SessionNames(), ui=ui)


def summary(view):
    return [(chip.name, chip.status, chip.wait_reason) for chip in view.all_chips]


@pytest.mark.parametrize(("inputs", "reason"), [
    (BoardInputs(cc_working=("cc",)), None),
    (BoardInputs(cc_holding=("cc",)), "checkpoint"),
    (BoardInputs(cc_permissions=("cc",)), "permission"),
    (BoardInputs(cc_working=("cc",), cc_holding=("cc",), cc_permissions=("cc", "cc")), "permission"),
])
def test_cc_active_states(inputs, reason):
    board = TaskBoard()
    assert summary(snapshot(board, inputs)) == [("会话 1", "waiting" if reason else "working", reason)]
    assert snapshot(board).all_chips == ()


@pytest.mark.parametrize("ended_by_shion", [True, False])
def test_cc_stop(ended_by_shion):
    board = TaskBoard()
    snapshot(board, cc_working=("cc",), now=1)
    board.note_cc_stop("cc", ended_by_shion=ended_by_shion, now=4)
    view = snapshot(board, now=100)
    if ended_by_shion:
        assert view.all_chips == ()
    else:
        chip, = view.all_chips
        assert (chip.key, chip.status, chip.started_at) == (CC, "done", 1)
        assert chip.tooltip.endswith("3s")
        resumed, = snapshot(board, cc_working=("cc",), now=101).all_chips
        board.dismiss_done(CC)
        assert resumed.key == CC and resumed.status == "working" and resumed.started_at == 101
        assert snapshot(board).all_chips == ()


def test_plan_ready_can_resume_or_be_dismissed():
    board = TaskBoard()
    snapshot(board, cc_working=("cc",), now=1)
    board.note_cc_plan_ready("cc", now=2)
    waiting = snapshot(board, now=3)
    assert summary(waiting) == [("会话 1", "waiting", "plan_ready")]
    assert waiting.all_chips[0].started_at == 1
    assert "计划待确认" in waiting.all_chips[0].tooltip
    board.clear_done()
    assert snapshot(board, now=4).all_chips[0].wait_reason == "plan_ready"
    assert summary(snapshot(board, cc_working=("cc",), now=5)) == [("会话 1", "working", None)]
    assert snapshot(board, now=6).all_chips == ()
    board.note_cc_plan_ready("cc", now=7)
    board.dismiss_plan(CC)
    assert snapshot(board, now=8).all_chips == ()


def test_plan_ready_yields_to_real_permission_and_checkpoint():
    board = TaskBoard()
    board.note_cc_plan_ready("cc", now=1)
    board.dismiss_plan(CHAT)
    assert snapshot(board, cc_holding=("cc",)).all_chips[0].wait_reason == "checkpoint"
    assert snapshot(board, cc_permissions=("cc",)).all_chips[0].wait_reason == "permission"
    assert snapshot(board).all_chips[0].wait_reason == "plan_ready"


@pytest.mark.parametrize("private", [True, False])
def test_legacy_cc_empty_session(private):
    board = TaskBoard()
    inputs = BoardInputs(cc_working=("", "cc"), cc_permissions=(None, ""), private=private)
    assert summary(snapshot(board, inputs)) == [
        ("Claude Code", "waiting", "permission"), ("会话 1", "working", None),
    ]
    board.note_cc_plan_ready("", now=1)
    assert summary(snapshot(board, private=private, now=2)) == [("Claude Code", "waiting", "plan_ready")]
    board.note_cc_stop("", ended_by_shion=False, now=3)
    assert summary(snapshot(board, private=private, now=4)) == [("Claude Code", "done", None)]


def test_chat_lifecycle():
    board = TaskBoard()
    activity = ChatActivity()

    def receive(event, now, client="desktop", name=None):
        notice = activity.receive(event, client, now)
        board.note_chat(notice, task_name=name, private=False, now=now)
        return snapshot(board, chat_phase=activity.phase, now=now)

    assert summary(receive("working", 1, name="做演示")) == [("做演示", "working", None)]
    assert summary(receive("need_input", 2)) == [("做演示", "waiting", "need_input")]
    assert summary(receive("done", 3, "other")) == [("做演示", "waiting", "need_input")]
    assert summary(receive("done", 4)) == [("做演示", "done", None)]
    assert summary(receive("working", 5, name="写摘要")) == [("写摘要", "working", None)]
    activity.expire(905)
    assert snapshot(board, chat_phase=activity.phase, now=905).all_chips == ()
    assert summary(receive("need_input", 906)) == [("Claude 聊天", "waiting", "need_input")]
    assert receive("offline", 907).all_chips == ()


def codex_event(ledger, event, *, session="codex", turn="1", **kwargs):
    ledger.accept(Observation(event, session_id=session, turn_id=turn, **kwargs))


def test_codex_permissions_and_loss():
    now = 1
    ledger = TaskLedger(clock=lambda: now, ttl=10)
    board = TaskBoard()

    def view():
        ledger.expire()
        return snapshot(board, ledger_tasks=ledger.tasks, ledger_ttl=ledger.ttl, now=now)

    codex_event(ledger, "PermissionRequest")
    assert next(iter(ledger.tasks.values())).state == "uncertain"
    assert summary(view()) == [("ChatGPT", "waiting", "permission_unknown")]
    now = 11
    assert view().all_chips == ()
    codex_event(ledger, "UserPromptSubmit", turn="2")
    assert summary(view()) == [("ChatGPT", "working", None)]
    codex_event(ledger, "PermissionRequest", turn="2")
    assert summary(view()) == [("ChatGPT", "waiting", "permission_unknown")]
    ledger.observation_gap()
    assert view().all_chips == ()
    ledger.disconnect()
    assert view().all_chips == ()


def test_codex_leased_permission_wait_expires():
    now = 1
    ledger = TaskLedger(clock=lambda: now, lease_ttl=4)
    board = TaskBoard()
    codex_event(ledger, "PermissionRequest", observer="local", leased=True)
    assert snapshot(board, ledger_tasks=ledger.tasks, now=now).all_chips[0].status == "waiting"
    now = 5
    ledger.expire()
    assert snapshot(board, ledger_tasks=ledger.tasks, now=now).all_chips == ()


def test_codex_dismissal_and_same_session_next_turn():
    now = 1
    ledger = TaskLedger(clock=lambda: now)
    board = TaskBoard()

    def view():
        return snapshot(board, ledger_tasks=ledger.tasks, now=now)

    codex_event(ledger, "UserPromptSubmit")
    assert summary(view()) == [("ChatGPT", "working", None)]
    now = 4
    codex_event(ledger, "Stop")
    assert summary(view()) == [("ChatGPT", "done", None)]
    assert view().all_chips[0].tooltip.endswith("3s")
    board.dismiss_done(CHATGPT)
    assert view().all_chips == ()
    now = 5
    codex_event(ledger, "UserPromptSubmit", turn="2")
    codex_event(ledger, "Interrupt")  # Late correction for turn 1.
    assert view().all_chips[0].key == CHATGPT
    assert summary(view()) == [("ChatGPT", "working", None)]
    codex_event(ledger, "Stop", turn="2")
    assert summary(view()) == [("ChatGPT", "done", None)]
    board.clear_done()
    assert view().all_chips == ()


def test_codex_interrupt_removes_a_previously_observed_completion():
    ledger = TaskLedger(clock=lambda: 1)
    board = TaskBoard()
    codex_event(ledger, "Stop")
    assert snapshot(board, ledger_tasks=ledger.tasks).all_chips[0].status == "done"
    codex_event(ledger, "Interrupt")
    assert snapshot(board, ledger_tasks=ledger.tasks).all_chips == ()


def test_done_capacity_uses_completion_time_and_does_not_revive_ledger_entries():
    ledger = TaskLedger(clock=lambda: 0)
    board = TaskBoard()
    codex_event(ledger, "Stop")
    snapshot(board, ledger_tasks=ledger.tasks)
    snapshot(board, cc_working=("0",), now=1)
    for n in range(1, 8):
        board.note_cc_stop(str(n), ended_by_shion=False, now=n + 1)
    before = snapshot(board, ledger_tasks=ledger.tasks, cc_working=("0",), now=8)
    assert sum(chip.status == "done" for chip in before.all_chips) == 8
    board.note_cc_stop("0", ended_by_shion=False, now=9)
    view = snapshot(board, ledger_tasks=ledger.tasks, now=10)
    assert len(view.all_chips) == 8
    assert view.all_chips[0].key == ("claude_code", "0")
    assert all(chip.key != CHATGPT for chip in view.all_chips)
    assert snapshot(TaskBoard()).all_chips == ()


def test_sort_overflow_and_clear_threshold():
    board = TaskBoard()
    ledger = TaskLedger(clock=lambda: 2)
    codex_event(ledger, "UserPromptSubmit")
    snapshot(board, ledger_tasks=ledger.tasks, cc_working=("earlier",), now=1)
    board.note_cc_stop("done1", ended_by_shion=False, now=1)
    board.note_cc_stop("done2", ended_by_shion=False, now=2)
    names = SessionNames()
    for session in ("wait", "earlier", "done1", "done2", "done3"):
        names.note(session, session)
    inputs = BoardInputs(cc_permissions=("wait",), cc_working=("earlier",), ledger_tasks=ledger.tasks)
    view = snapshot(board, inputs, now=3, names=names)
    assert summary(view) == [
        ("wait", "waiting", "permission"), ("earlier", "working", None),
        ("ChatGPT", "working", None), ("done1", "done", None), ("done2", "done", None),
    ]
    assert view.visible_chips == view.all_chips[:4] and view.overflow_count == 1
    assert view.all_chips[1].started_at < view.all_chips[2].started_at
    assert not view.show_clear_done
    board.note_cc_stop("done3", ended_by_shion=False, now=3)
    assert snapshot(board, inputs, now=4).show_clear_done
    board.clear_done()
    view = snapshot(board, replace(inputs, cc_working=("earlier", "new")), now=5)
    assert len(view.visible_chips) == 4 and view.overflow_count == 0
    assert not view.show_clear_done


def test_privacy_names_and_link_isolation():
    board = TaskBoard()
    names = SessionNames()
    names.note("cc", "project", "prompt one")
    names.note("other", "project", "prompt two")
    board.note_cc_stop("cc", ended_by_shion=False, now=1)
    board.note_chat("working", task_name="聊天名称", private=False, now=2)
    board.note_chat("done", private=False, now=3)
    ledger = TaskLedger(clock=lambda: 3)
    codex_event(ledger, "UserPromptSubmit", session="one")
    codex_event(ledger, "UserPromptSubmit", session="two")
    inputs = BoardInputs(cc_working=("other",), ledger_tasks=ledger.tasks)
    public = snapshot(board, inputs, names=names, now=4)
    assert {chip.name for chip in public.all_chips} == {
        "project · prompt one", "project · prompt two", "聊天名称", "ChatGPT", "ChatGPT 2",
    }
    private = snapshot(board, replace(inputs, private=True), names=names, now=5)
    assert {chip.name for chip in private.all_chips} == {"会话 1", "会话 2", "Claude 聊天", "ChatGPT", "ChatGPT 2"}
    assert all(word not in chip.tooltip for chip in private.all_chips for word in ("project", "prompt", "聊天名称"))
    cc_off = snapshot(board, replace(inputs, cc_link_enabled=False), names=names, now=6)
    assert summary(cc_off) == [
        ("ChatGPT", "working", None), ("ChatGPT 2", "working", None), ("Claude 聊天", "done", None),
    ]


def test_import_does_not_load_qt():
    subprocess.run(
        [sys.executable, "-c",
         "import sys, shion.task_board; assert not any(n.startswith('PySide') for n in sys.modules)"],
        check=True,
    )
