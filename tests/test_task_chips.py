import os
from datetime import timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QBitmap, QRegion
from PySide6.QtTest import QTest

from shion import v3_window
from shion.app import SnapshotScene, render_snapshot
from shion.chatgpt import ChatGPTConnection
from shion.events import Observation
from shion.lines import Lines
from shion.sessions import SessionNames
from shion.state import SaveData
from shion.task_board import BoardInputs, TaskBoard
from shion.task_chips import GAP, ROW, SPACING, TaskChips, place_chips
from shion.tasks import TaskLedger
from shion.v3_prewarm import InlineExecutor
from tests.test_controller import env, qapp


AVAIL = QRect(-1440, 0, 1440, 900)


def render_view(count=1):
    return TaskBoard().snapshot(BoardInputs(cc_working=tuple(map(str, range(count)))),
                                now=10, session_names=SessionNames(), ui=Lines("zh").ui)


@pytest.mark.parametrize("height", [160, 200, 260, 320])
@pytest.mark.parametrize("pose", ["idle", "bed", "desk"])
def test_chip_rect_never_intersects_visible_pet(qapp, monkeypatch, height, pose):
    monkeypatch.setattr(v3_window, "PREWARM_EXECUTOR", InlineExecutor())
    with SnapshotScene(pose, height=height, side="right") as scene:
        pet = scene.win
        pet.show()
        scene.advance_to(0.6)
        if pose != "idle":
            assert pet._v3_scene_shown is not None
        if pose == "bed":
            assert pet.sprite_size[0] > pet.normal_width
        chips = TaskChips(pet, available=lambda _point: AVAIL)
        chips.setAttribute(Qt.WA_DontShowOnScreen)
        try:
            for center, on_right in ((-1050, True), (-390, False)):
                pet.move(center - pet.width() // 2, 260)
                chips.present(render_view(5), Lines("zh").ui)
                assert chips.isVisible()
                rect = chips.geometry()
                assert AVAIL.contains(rect)
                input_region = pet.mask().translated(pet.pos())
                assert not input_region.isEmpty()
                assert input_region.intersected(QRegion(rect)).isEmpty()

                # Check the rendered pixels independently of the layout bounds.
                frame = pet.render_scene_frame(clip=True)
                canvas = pet.geometry()
                overlay = pet._v3_scene_overlay
                if overlay is not None and overlay.isVisible():
                    canvas = canvas.united(overlay.geometry())
                bitmap = QBitmap.fromImage(frame.createMaskFromColor(0, Qt.MaskInColor))
                visible_region = QRegion(bitmap).translated(canvas.topLeft())
                assert not visible_region.isEmpty()
                assert visible_region.intersected(QRegion(rect)).isEmpty()
                visible = visible_region.boundingRect()
                gap = rect.left() - visible.right() - 1 if on_right else visible.left() - rect.right() - 1
                assert 8 <= gap <= 12
        finally:
            chips.hide()
            chips.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_layout_offsets_around_obstacles_and_rejects_unsafe_space():
    body = QRect(-1030, 320, 250, 200)
    pet = body.adjusted(-15, -20, 15, 20)
    size = QSize(192, 146)
    right = pet.right() + GAP + 1
    panels = (QRect(right, 0, 240, 350), QRect(right, 350, 220, 220))
    shifted = place_chips(body, pet, size, AVAIL, panels, "right")
    assert shifted.left() == right and shifted.top() == 570 + GAP
    assert all(not shifted.intersects(obstacle) for obstacle in (*panels, pet))
    full_right = QRect(right, 0, 300, AVAIL.height())
    alternate = place_chips(body, pet, size, AVAIL, (full_right,), "right")
    assert alternate.right() < pet.left()
    full_left = QRect(AVAIL.x(), 0, pet.x() - AVAIL.x(), AVAIL.height())
    assert place_chips(body, pet, size, AVAIL, (full_left, full_right), "right") is None


def test_overflow_is_mouse_only_and_does_not_activate_window(qapp):
    from PySide6.QtWidgets import QWidget
    class Pet(QWidget):
        visible_sprite_bounds_changed = Signal()

        def visible_sprite_bounds(self):
            return self.geometry()

        resting_sprite_bounds = visible_sprite_bounds

        def body_rect(self):
            return self.geometry().getRect()

    pet = Pet()
    pet.setAttribute(Qt.WA_DontShowOnScreen)
    pet.setGeometry(-1020, 270, 250, 260)
    pet.is_dragging = pet.is_falling = pet.lifting = False
    chips = TaskChips(pet, available=lambda _point: AVAIL)
    chips.setAttribute(Qt.WA_DontShowOnScreen)
    try:
        pet.show()
        chips.present(render_view(10), Lines("zh").ui)
        pos = QPoint(70, 4 * (ROW + SPACING) + 12)
        QTest.mouseClick(chips, Qt.RightButton, pos=pos)
        assert not chips.expanded
        QTest.mouseClick(chips, Qt.LeftButton, pos=pos)
        assert chips.expanded and len(chips._shown_chips) > 4
        assert not chips.isActiveWindow()
        for attr in ("is_dragging", "lifting", "is_falling"):
            setattr(pet, attr, True)
            chips.follow()
            assert not chips.isVisible()
            setattr(pet, attr, False)
            chips.follow()
            assert chips.isVisible()
        pet.hide()
        assert not chips.isVisible()
    finally:
        chips.deleteLater()
        pet.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_legacy_plan_and_interrupted_stop_reach_view(env):
    controller = env.ctl
    controller.handle_event("prompt")
    chips = controller._task_chips
    assert chips.view.all_chips[0].name == "Claude Code"
    controller.handle_event("plan_ready")
    assert chips.view.all_chips[0].wait_reason == "plan_ready"
    controller.handle_event("working")
    assert chips.view.all_chips[0].status == "working"
    controller.handle_event("work_stopped")
    controller.handle_event("stop")
    assert chips.view is None
    controller.handle_event("prompt", meta={"session": "named", "project": "demo"})
    controller.handle_event("stop", meta={"session": "named"})
    assert [(item.name, item.status) for item in chips.view.all_chips] == [("demo", "done")]
    controller.toggle_claude_link()
    assert chips.view is None


@pytest.mark.parametrize("ended_event", ["work_stopped", "pause_timeout"])
@pytest.mark.parametrize("legacy_meta", [None, {"session": ""}])
def test_legacy_turn_ended_by_shion_does_not_count_as_completion(env, ended_event, legacy_meta):
    controller = env.ctl
    day = str(env.now.date())
    controller.handle_event("prompt", meta=legacy_meta)
    chips = controller._task_chips
    assert chips.view.all_chips[0].status == "working"
    controller.handle_event(ended_event, meta=legacy_meta)
    assert "" in controller._end_pending
    controller.handle_event("stop", meta=legacy_meta)
    assert "" not in controller._end_pending
    assert chips.view is None
    assert env.data.stats["claude_tasks"] == 0
    assert env.data.weekly_stats.get(day, {}).get("tasks", 0) == 0

    controller.handle_event("prompt", meta=legacy_meta)
    controller.handle_event("stop", meta=legacy_meta)
    chip, = chips.view.all_chips
    assert chip.name == "Claude Code" and chip.status == "done"
    assert env.data.stats["claude_tasks"] == env.data.weekly_stats[day]["tasks"] == 1


def test_completed_chip_stays_put_during_animation_and_follows_real_move(env):
    pet = env.win
    pet.setAttribute(Qt.WA_DontShowOnScreen)
    pet.auto_side = False
    pet.show()
    env.ctl.handle_event("prompt", meta={"session": "demo"})
    chips = env.ctl._task_chips
    assert chips.isVisible()
    before = chips.geometry()
    original_pos = pet.pos()

    env.ctl.handle_event("stop", meta={"session": "demo"})
    pet.jump()  # Completion and the jump are separate in the window animation.
    saw_jump = False
    for duration in (0.05, 0.10, 0.10, 0.12, 0.24, 0.55):
        env.advance(duration)
        saw_jump |= pet._jump_offset > 0
        assert pet.pos() == original_pos
        assert chips.isVisible() and chips.geometry() == before
    assert saw_jump
    offset = QPoint(-9, -9)
    pet.move(original_pos + offset)
    env.ctl.sync()
    assert chips.geometry() == before.translated(offset)


def test_chip_first_shown_at_jump_peak_uses_resting_position(env):
    pet = env.win
    pet.setAttribute(Qt.WA_DontShowOnScreen)
    pet.auto_side = False
    pet.show()
    pet.jump()
    env.advance(0.16)
    assert pet._jump_offset > 0
    env.ctl.handle_event("prompt")
    chips = env.ctl._task_chips
    rectangle = chips.geometry()
    assert chips.isVisible()
    env.advance(0.8)
    assert pet._jump_offset == 0
    assert chips.isVisible() and chips.geometry() == rectangle


def _click_chip(chips, index):
    QTest.mouseClick(chips, Qt.LeftButton, pos=QPoint(70, index * (ROW + SPACING) + ROW // 2))


def test_chip_clicks_dismiss_waiting_plan_and_completed_items_in_overflow(env):
    env.win.setAttribute(Qt.WA_DontShowOnScreen)
    env.win.show()
    controller = env.ctl
    for n in range(5):
        controller.handle_event("stop", meta={"session": f"finished-{n}"})
    controller.handle_event("plan_ready", meta={"session": "plan"})
    controller.handle_event("prompt", meta={"session": "working"})
    chips = controller._task_chips
    assert chips.isVisible()
    _click_chip(chips, 0)  # Awaiting plan.
    assert all(chip.wait_reason != "plan_ready" for chip in chips.view.all_chips)
    _click_chip(chips, 0)  # Working row is informational.
    assert chips.view.all_chips[0].status == "working"
    _click_chip(chips, 4)  # Open the overflow list.
    assert chips.expanded and len(chips._shown_chips) == 6
    _click_chip(chips, 5)  # A completion from the formerly hidden rows.
    assert all(chip.key != ("claude_code", "finished-4") for chip in chips.view.all_chips)
    clear = len(chips._shown_chips) + int(bool(chips.view.overflow_count))
    _click_chip(chips, clear)
    assert [chip.status for chip in chips.view.all_chips] == ["working"]


def test_permission_chip_only_raises_the_queue_head(env, monkeypatch):
    from shion import controller as module

    env.win.setAttribute(Qt.WA_DontShowOnScreen)
    env.win.show()
    controller = env.ctl
    first = controller.hub.permissions.open("Bash", "git status", session="first")
    second = controller.hub.permissions.open("Write", "C:/demo/file", session="second")
    env.advance(0.1)
    chips = controller._task_chips
    assert chips.isVisible()
    raised = []
    monkeypatch.setattr(module, "raise_without_activation", raised.append)
    index = next(i for i, chip in enumerate(chips.view.visible_chips)
                 if chip.key == ("claude_code", "second"))
    _click_chip(chips, index)
    assert raised == [controller._perm_panel]
    assert controller._perm_panel.request_id == first
    assert [request.id for request in controller.hub.permissions.pending()] == [first, second]
    assert all(request.status == "pending" for request in controller.hub.permissions.pending())


def test_checkpoint_chip_raises_pause_badge_without_resuming(env, monkeypatch):
    from shion import controller as module

    env.win.setAttribute(Qt.WA_DontShowOnScreen)
    env.win.show()
    ctl = env.ctl
    ctl.handle_event("prompt", meta={"session": "held"})
    ctl.stop_work("held")
    assert ctl.hub.wait_gate(0, "held") == (True, False)
    env.advance(0.1)
    chips = ctl._task_chips
    assert chips.isVisible() and chips.view.visible_chips[0].wait_reason == "checkpoint"
    assert env.win._pause_badge.isVisible()
    raised = []
    monkeypatch.setattr(module, "raise_without_activation", raised.append)
    _click_chip(chips, 0)
    assert raised == [env.win._pause_badge]
    assert ctl.hub.is_session_paused("held")


def test_chat_wait_chip_points_to_the_observed_app(env):
    env.win.setAttribute(Qt.WA_DontShowOnScreen)
    env.win.show()
    env.ctl.handle_event("chat_event", meta={"event": "need_input", "client": "demo"})
    env.ctl._speech.dismiss()
    chips = env.ctl._task_chips
    assert chips.isVisible()
    _click_chip(chips, 0)
    assert env.said[-1] == env.ctl.lines.ui("task_board_check_claude_chat")


def test_working_chip_shows_current_turn_and_tool_without_exposing_private_text(env):
    env.win.setAttribute(Qt.WA_DontShowOnScreen)
    env.win.show()
    ctl = env.ctl
    ctl.handle_event("prompt", meta={"session": "one", "project": "chips-c", "prompt_head": "修改 hello.py"})
    ctl.handle_event("prompt", meta={"session": "two", "project": "other", "prompt_head": "检查文档"})
    chips = ctl._task_chips
    first, second = chips.view.all_chips
    assert (first.activity, second.activity) == ("修改 hello.py", "检查文档")

    ctl.handle_event("working", '{"tool":"edit","target":"hello.py"}', {"session": "one", "tool_id": "edit"})
    first, second = chips.view.all_chips
    assert "在改 hello.py" in first.activity and "chips-c" in first.tooltip
    assert second.activity == "检查文档"
    assert "在改 hello.py" in chips._rows[0][0]

    ctl.handle_event("tool_done", meta={"session": "one", "tool_id": "older"})
    assert "在改 hello.py" in chips.view.all_chips[0].activity
    ctl.handle_event("tool_done", meta={"session": "one", "tool_id": "edit"})
    assert chips.view.all_chips[0].activity == "修改 hello.py"
    ctl.handle_event("prompt", meta={"session": "one", "prompt_head": "再跑一次测试"})
    assert chips.view.all_chips[0].activity == "再跑一次测试"

    ctl.set_privacy(True)
    assert all(not item.activity for item in chips.view.all_chips)
    assert "再跑一次测试" not in chips.view.all_chips[0].tooltip
    ctl.set_privacy(False)
    assert all(not item.activity for item in chips.view.all_chips)


def test_settings_and_privacy_refresh_live_view(env):
    controller = env.ctl
    assert SaveData.from_dict({}).show_task_chips
    controller.handle_event("prompt", meta={"session": "demo", "project": "private-name"})
    controller.set_muted(True)
    chips = controller._task_chips
    assert chips.view.all_chips[0].name == "private-name"
    controller.set_privacy(True)
    assert chips.view.all_chips[0].name == "会话 1"
    assert "private-name" not in chips.view.all_chips[0].tooltip
    controller.set_show_task_chips(False)
    assert not SaveData.from_dict(env.data.to_dict()).show_task_chips
    controller.handle_event("stop", meta={"session": "demo"})
    assert chips.view is None
    controller.set_show_task_chips(True)
    controller.set_language("en")
    chip, = chips.view.all_chips
    assert chip.status == "done" and chip.name == "Session 1"
    assert "Ended" in chip.tooltip


def test_desktop_chat_done_and_timeout(env):
    controller = env.ctl
    controller.handle_event("chat_event", "Slides", {"event": "working", "client": "demo"})
    chips = controller._task_chips
    assert chips.view.all_chips[0].name == "Slides"
    controller.handle_event("chat_event", meta={"event": "done", "client": "other"})
    assert chips.view.all_chips[0].status == "working"
    controller.handle_event("chat_event", meta={"event": "done", "client": "demo"})
    assert chips.view.all_chips[0].status == "done"
    controller.handle_event("chat_event", "Next", {"event": "working", "client": "demo"})
    env.mono[0] += 901
    env.now += timedelta(seconds=901)
    controller.tick()
    assert chips.view is None


def test_chatgpt_uses_observer_clock_and_reuses_label(env, tmp_path):
    controller = env.ctl
    controller.chatgpt = ChatGPTConnection(tmp_path / "data", tmp_path / "codex")
    ledger_clock = [20_000.0]
    ledger = controller.chatgpt.ledger = TaskLedger(clock=lambda: ledger_clock[0])
    ledger.accept(Observation("PermissionRequest", "session", "first"))
    controller.tick()
    chips = controller._task_chips
    before, = chips.view.all_chips
    assert before.wait_reason == "permission_unknown"
    env.mono[0] += 5
    ledger_clock[0] += 5
    ledger.accept(Observation("Stop", "session", "first"))
    controller.tick()
    done, = chips.view.all_chips
    assert done.status == "done" and "5 秒" in done.tooltip
    ledger.accept(Observation("UserPromptSubmit", "session", "second"))
    controller.tick()
    after, = chips.view.all_chips
    assert after.key == before.key and after.status == "working"


@pytest.mark.parametrize("side,overlays", [("right", "pause"), ("left", "checkpoints")])
def test_snapshot_composes_chip_preview(qapp, side, overlays):
    image = render_snapshot(state="desk", height=260, at=0.6, chips="demo",
                            chips_side=side, chips_overlays=overlays)
    assert not image.isNull()
    assert image.width() > 400
