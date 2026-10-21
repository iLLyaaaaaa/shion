"""抱胸待机与独立动作边界：真实时间混合、排除项和并集轮廓。"""
import math
from dataclasses import replace

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest

from shion.animator import Frame, TRANSITION, ease_out
from shion.behavior import (
    CHEEK_RELEASE_SECONDS, FACE_SECONDS, JUMP_DURATION, TURN_FRAME_SECONDS,
)
from shion.pet_window import ACTION_FADE_SECONDS, MARGIN_BOTTOM, MARGIN_TOP, MARGIN_X, PetWindow
from tests.test_controller import BODY, qapp
from tests.test_feedback_ui import move_global, pixels


@pytest.fixture
def scene(qapp):
    clock = [100.0]
    w = PetWindow(clock=lambda: clock[0], autostart=False)
    w.set_activity("quiet")  # 只隔离随机微动作；呼吸和眨眼仍正常运行。
    w.set_state("idle", animate=False)
    w._animator._next_blink = math.inf
    w.move(400, 200)

    def advance(elapsed):
        clock[0] = 100 + elapsed
        w.advance_to(clock[0])

    yield w, clock, advance
    w.close()


def start(w, action):
    if action == "face_left":
        w.face(-1)
    elif action == "face_right":
        w.face(1)
    else:
        getattr(w, action)()


def layers(frame):
    return dict(frame.layers or ((frame.sprite, 1.0),))


@pytest.mark.parametrize("action,first,end,last", [
    ("turn", "turn_1", 8 * TURN_FRAME_SECONDS, "turn_8"),
    ("jump", "jump_1", JUMP_DURATION, "jump_4"),
    ("face_left", "turn_8", FACE_SECONDS, "turn_8"),
    ("face_right", "turn_2", FACE_SECONDS, "turn_2"),
])
def test_both_boundaries_have_exact_duration_without_delaying_action(scene, action, first, end, last):
    w, _, advance = scene
    start(w, action)
    assert w.displayed_sprite == first
    assert layers(w.frame) == {"idle": 1.0}
    advance(ACTION_FADE_SECONDS / 2)
    assert layers(w.frame) == pytest.approx({"idle": .5, first: .5})
    advance(ACTION_FADE_SECONDS)
    assert layers(w.frame) == {w.displayed_sprite: 1.0}
    assert w._action_fade is None
    advance(end)
    assert not w.motion_active and w.displayed_sprite == "idle"
    assert layers(w.frame) == {last: 1.0}
    advance(end + ACTION_FADE_SECONDS / 2)
    assert layers(w.frame) == pytest.approx({last: .5, "idle": .5})
    advance(end + ACTION_FADE_SECONDS)
    assert layers(w.frame) == {"idle": 1.0} and w._action_fade is None


def test_turn_internal_frames_do_not_restart_boundary_fade(scene):
    w, _, advance = scene
    w.turn()
    advance(TURN_FRAME_SECONDS)
    assert layers(w.frame) == pytest.approx({"idle": .1, "turn_2": .9})
    for i in range(2, 8):
        advance(i * TURN_FRAME_SECONDS)
        assert layers(w.frame) == {f"turn_{i + 1}": 1.0}


@pytest.mark.parametrize("action,end,last", [("turn", .72, "turn_8"), ("jump", JUMP_DURATION, "jump_4"),
                                           ("face_right", FACE_SECONDS, "turn_2")])
def test_sparse_end_uses_scheduled_last_frame_and_never_replays_fade(scene, action, end, last):
    w, _, advance = scene
    start(w, action)
    # 没有画过任何中间动作帧，直接越过结束点。
    advance(end + .05)
    assert layers(w.frame) == pytest.approx({last: .5, "idle": .5})
    advance(end + 1)
    assert layers(w.frame) == {"idle": 1.0} and w._action_fade is None


@pytest.mark.parametrize("action", ["turn", "jump", "face_left"])
def test_interrupt_and_fast_restart_continue_the_current_mix(scene, action):
    w, clock, advance = scene
    start(w, action)
    advance(.04)
    before = layers(w.frame)
    w.stop_motion()
    assert not w.motion_active and layers(w.frame) == pytest.approx(before)
    advance(.065)
    outgoing = {name: weight * .75 for name, weight in before.items()}
    outgoing["idle"] += .25
    assert layers(w.frame) == pytest.approx(outgoing)
    w.face(1)
    assert layers(w.frame) == pytest.approx(outgoing)
    advance(clock[0] - 100 + ACTION_FADE_SECONDS)
    assert layers(w.frame) == {"turn_2": 1.0}
    assert w._action_fade is None


def test_blink_source_is_preserved_but_blink_itself_has_no_action_fade(scene):
    w, clock, advance = scene
    w._animator._next_blink = 100
    w._animator._rng.seed(0)  # 不触发双眨眼。
    advance(.06)
    source = layers(w.frame)
    assert set(source) == {"idle", "blink"} and w._action_fade is None
    w.face(1)
    assert layers(w.frame) == pytest.approx(source)
    advance(.06 + ACTION_FADE_SECONDS / 2)
    expected = {name: weight * .5 for name, weight in source.items()}
    expected["turn_2"] = .5
    assert layers(w.frame) == pytest.approx(expected)


@pytest.mark.parametrize("state", ["working", "happy", "proud", "sleep", "bed"])
def test_expression_switch_cancels_boundary_fade_and_keeps_original_transition(scene, state):
    w, clock, advance = scene
    w.turn()
    advance(.04)
    w.stop_motion()
    w.set_state(state)
    assert w._action_fade is None
    assert not any(name.startswith("turn_") for name in layers(w.frame))
    advance(clock[0] - 100 + TRANSITION / 2)
    target = "bed_1" if state == "bed" else state
    assert layers(w.frame) == pytest.approx({"idle": 1 - ease_out(.5), target: ease_out(.5)})


@pytest.mark.parametrize("state", ["working", "happy", "neglect1"])
def test_actions_on_other_expressions_do_not_add_boundary_fade(scene, state):
    w, _, advance = scene
    w.set_state(state, animate=False)
    w.face(1)
    assert layers(w.frame) == {"turn_2": 1.0} and w._action_fade is None
    advance(FACE_SECONDS)
    assert layers(w.frame) == {state: 1.0} and w._action_fade is None


def test_real_drag_clears_interrupted_action_and_stays_immediate_on_release(scene):
    w, _, advance = scene
    w.turn()
    advance(.04)
    QTest.mousePress(w, Qt.LeftButton, Qt.NoModifier, BODY)
    gp = w.mapToGlobal(BODY)
    move_global(w, gp + QPoint(25, -25))
    advance(.05)
    assert w.is_dragging and layers(w.frame) == {"drag_1": 1.0}
    assert w._action_fade is None
    advance(.30)  # 原地停住再慢放，避免触发甩出。
    QTest.mouseRelease(w, Qt.LeftButton, Qt.NoModifier, w.mapFromGlobal(gp + QPoint(25, -25)))
    assert not w.is_falling and not w.is_dragging
    assert not any(name.startswith(("turn_", "drag_")) for name in layers(w.frame))
    assert w._action_fade is None


def test_legacy_jump_without_action_frames_has_no_boundary_fade(scene):
    w, _, advance = scene
    w._sequences.pop("jump")
    w.jump()
    advance(.25)
    assert w._jump_offset > 0
    assert layers(w.frame) == {"idle": 1.0} and w._action_fade is None
    advance(.5)
    assert not w.motion_active and w._action_fade is None


def test_cheek_gesture_enters_and_exits_but_direction_and_release_frames_are_direct(scene):
    w, _, advance = scene
    cheek = QPoint(MARGIN_X + w.sprite_size[0] // 2, MARGIN_TOP + round(w.sprite_size[1] * .47))
    QTest.mousePress(w, Qt.LeftButton, Qt.NoModifier, cheek)
    gp = w.mapToGlobal(cheek)
    move_global(w, gp + QPoint(15, 0))
    advance(.05)
    assert layers(w.frame) == pytest.approx({"idle": .5, "cheek_1": .5})
    advance(.11)
    move_global(w, gp + QPoint(-15, 0))
    assert layers(w.frame) == {"cheek_2": 1.0}
    QTest.mouseRelease(w, Qt.LeftButton, Qt.NoModifier, w.mapFromGlobal(gp + QPoint(-15, 0)))
    assert layers(w.frame) == {"cheek_3": 1.0}
    advance(.11 + CHEEK_RELEASE_SECONDS + .05)
    assert layers(w.frame) == pytest.approx({"cheek_3": .5, "idle": .5})


def test_tickle_loop_and_scheduled_end_use_only_boundary_fades(scene):
    w, _, advance = scene
    w._feed_tickle(100)
    advance(.05)
    assert layers(w.frame) == pytest.approx({"idle": .5, "tickle_1": .5})
    advance(.2)
    assert layers(w.frame) == {"tickle_2": 1.0}
    advance(1.05)
    assert layers(w.frame) == pytest.approx({"tickle_3": .5, "idle": .5})


@pytest.mark.parametrize("height", [160, 200, 260, 320])
@pytest.mark.parametrize("action,end", [("turn", .72), ("jump", JUMP_DURATION), ("face_right", FACE_SECONDS)])
def test_transition_mask_is_full_union_and_covers_all_pixels_without_moving_feet(scene, height, action, end):
    w, _, advance = scene
    w.set_height(height)
    anchor = (w.x() + w.width() / 2, w.y() + w.height() - MARGIN_BOTTOM)
    start(w, action)
    for t in (.001, .05, .099, end + .001, end + .05, end + .099, end + .11):
        advance(t)
        f = w.frame
        actual = w.mask()
        for name in layers(f):
            single = replace(f, sprite=name, layers=())
            assert (w._mask_for(single) - actual).isEmpty()
        a = pixels(w)[:, :, 3]
        ys, xs = np.where(a > 0)
        assert all(actual.contains(QPoint(int(x), int(y))) for x, y in zip(xs, ys))
        assert not actual.contains(QPoint(0, 0))
        assert xs.min() > 0 and xs.max() < a.shape[1] - 1
        assert ys.min() > 0 and ys.max() < a.shape[0] - 1
        assert anchor == (w.x() + w.width() / 2, w.y() + w.height() - MARGIN_BOTTOM)
        # 上面的单帧查询会切换内部缓存键，恢复真实显示帧。
        w._mask_for(f)


def test_opacity_only_changes_reuse_union_mask_and_opaque_overlap_does_not_flash(scene):
    w, _, advance = scene
    w._pixmaps["idle"].fill(QColor("red"))
    w._pixmaps["turn_2"].fill(QColor("blue"))
    w._mask_cache.clear()
    w._mask_key = None
    w.face(1)
    advance(.025)
    mask, count = w.mask(), len(w._mask_cache)
    advance(.05)
    assert w.mask() == mask and len(w._mask_cache) == count
    color = w.render_frame().pixelColor(w.width() // 2, MARGIN_TOP + 80)
    assert color.alpha() == 255 and abs(color.red() - color.blue()) <= 1


@pytest.mark.parametrize("motion,end", [("--turn", .72), ("--jump", JUMP_DURATION), ("--face", FACE_SECONDS)])
def test_snapshot_cli_captures_both_boundary_midpoints(qapp, tmp_path, motion, end):
    from shion.__main__ import main
    args = [motion, "right"] if motion == "--face" else [motion]
    images = []
    for t in (0, .05, .1, end, end + .05, end + .1):
        out = tmp_path / f"{motion}-{t}.png"
        assert main(["--snapshot", str(out), "--activity", "quiet", *args, "--at", str(t)]) == 0
        img = QImage(str(out)).convertToFormat(QImage.Format_RGBA8888)
        images.append(bytes(img.constBits()))
    assert images[0] != images[1] != images[2]
    assert images[3] != images[4] != images[5]
