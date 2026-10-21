"""帧序列、缺图回退、脚底锚点及遮罩的集成测试。"""
import math
import shutil

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest

from shion.animator import SQUASH, WORKING_BREATH_AMP, WORKING_BREATH_PERIOD
from shion.behavior import (
    JUMP_AIR_DURATION, JUMP_CROUCH_DURATION, JUMP_DURATION, JUMP_HEIGHT,
    JUMP_RISE_DURATION, JUMP_HOLD_DURATION, JUMP_FALL_DURATION,
    LEGACY_JUMP_DURATION, LEGACY_JUMP_HEIGHT,
)
from shion.pet_window import PetWindow, SPRITE_DIR, STATES
from tests.test_controller import BODY, env, qapp
from tests.test_feedback_ui import pixels

SEQUENCES = {group: tuple(f"{group}_{i}" for i in range(1, count + 1))
             for group, count in (("turn", 8), ("jump", 4), ("drag", 4), ("cheek", 3), ("tickle", 3))}


def working_breath(elapsed):
    return 1 + WORKING_BREATH_AMP / 2 * (1 - math.cos(2 * math.pi * elapsed / WORKING_BREATH_PERIOD))


@pytest.mark.parametrize("automatic", [False, True])
def test_jump_four_stages_45px_then_lands_with_squash_and_rebound(env, automatic):
    w = env.win
    w.set_state("working", animate=False)
    pos = w.pos()
    w.jump(automatic=automatic)
    assert w.displayed_sprite == "jump_1" and w._jump_offset == 0
    assert w.idle_motion_active == automatic
    for elapsed, sprite, height in (
        (0.149, "jump_1", 0), (JUMP_CROUCH_DURATION, "jump_2", 0),
        (JUMP_CROUCH_DURATION + JUMP_RISE_DURATION / 2, "jump_2", JUMP_HEIGHT * 0.875),
        (JUMP_CROUCH_DURATION + JUMP_RISE_DURATION, "jump_3", JUMP_HEIGHT),
        (JUMP_CROUCH_DURATION + JUMP_RISE_DURATION + JUMP_HOLD_DURATION, "jump_4", JUMP_HEIGHT),
        (JUMP_DURATION - JUMP_FALL_DURATION / 2, "jump_4", JUMP_HEIGHT * 0.75),
        (JUMP_DURATION, "working", 0),
    ):
        env.mono[0] = 100 + elapsed
        w.advance_to(env.mono[0])
        assert w.displayed_sprite == sprite
        assert w._jump_offset == pytest.approx(height, abs=1e-8)
        assert w.pos() == pos
    land = SQUASH["jump_land"][0]
    w.advance_to(100 + JUMP_DURATION + land * 0.3)
    assert w.frame.sy == pytest.approx(SQUASH["jump_land"][1] * working_breath(JUMP_DURATION + land * .3), abs=0.001)
    w.advance_to(100 + JUMP_DURATION + land * 0.8)
    assert w.frame.sy > 1
    w.advance_to(100 + JUMP_DURATION + land + 0.01)
    assert not w.motion_active and w.displayed_sprite == "working"
    assert w.frame.sy == pytest.approx(working_breath(JUMP_DURATION + land + .01), abs=.001)
    assert w.frame.sx == 1 and w.frame.angle == 0


@pytest.mark.parametrize("action,elapsed", [("turn", 0.47), ("jump", 0.35), ("jump", 0.625), ("jump", 1.0)])
def test_motion_does_not_depend_on_dropped_frames(qapp, action, elapsed):
    windows = [PetWindow(clock=lambda: 100.0, autostart=False) for _ in range(2)]
    try:
        for w in windows:
            w.set_state("working", animate=False)
            w.place_default()
            w.turn() if action == "turn" else w.jump()
        for i in range(1, int(elapsed * 60) + 1):
            windows[0].advance_to(100 + i / 60)
        for w in windows:
            w.advance_to(100 + elapsed)
        a, b = windows
        assert a.frame == b.frame and a.pos() == b.pos()
        assert a._jump_offset == pytest.approx(b._jump_offset)
        assert np.array_equal(pixels(a), pixels(b))
    finally:
        for w in windows:
            w.close()


@pytest.mark.parametrize("missing", ["turn_2", "turn_8", "tickle_3", "cheek_3", "jump_1", "jump_2", "drag_2"])
@pytest.mark.parametrize("problem", ["absent", "corrupt", "wrong_canvas"])
def test_optional_group_falls_back_as_a_whole(qapp, tmp_path, monkeypatch, missing, problem):
    import shion.pet_window as module
    for name in STATES + [name for names in SEQUENCES.values() for name in names]:
        if name != missing:
            shutil.copyfile(SPRITE_DIR / f"{name}.png", tmp_path / f"{name}.png")
    broken = tmp_path / f"{missing}.png"
    if problem == "corrupt":
        broken.write_bytes(b"not a png")
    elif problem == "wrong_canvas":
        image = QImage(20, 20, QImage.Format_ARGB32)
        image.fill(Qt.red)
        assert image.save(str(broken))
    monkeypatch.setattr(module, "SPRITE_DIR", tmp_path)
    w = PetWindow(clock=lambda: 100.0, autostart=False)
    try:
        group = missing.split("_")[0]
        assert group not in w._sequences
        assert all(name not in w._pixmaps for name in SEQUENCES[group])
        assert ("jump" if group == "turn" else "turn") in w._sequences
        w.set_state("working", animate=False)
        if group == "jump":
            w.jump()
            w.advance_to(100 + LEGACY_JUMP_DURATION / 2)
            assert w.displayed_sprite == "working"
            assert w._jump_offset == pytest.approx(LEGACY_JUMP_HEIGHT)
            w.advance_to(100 + LEGACY_JUMP_DURATION)
            assert not w.motion_active and w._jump_offset == 0
        elif group in ("turn", "tickle", "cheek"):
            if group == "turn":
                w.turn()
                assert not w.motion_active and w.displayed_sprite == "working"
            elif group == "tickle":
                w._feed_tickle(100)
                assert w.displayed_sprite == "happy"
            else:
                assert w._gesture_sprite("cheek", 3, "stop") == "stop"
        else:
            from shion.behavior import DragPlayback
            w.set_state("drag", animate=False)
            w._drag_playback = DragPlayback(100)
            w.advance_to(100.22)
            assert w.displayed_sprite == "drag"
    finally:
        w.close()


@pytest.mark.parametrize("height", [160, 200, 260, 320])
def test_motion_pixels_are_not_clipped_and_masks_cover_visible_pixels(env, height):
    w = env.win
    w.set_height(height)
    w.set_state("working", animate=False)
    w.place_default()
    for action, times in (("turn", [i * 0.09 for i in range(8)]),
                          ("jump", [0, 0.075, 0.15, 0.24, 0.35, 0.44, 0.495, 0.625])):
        w.turn() if action == "turn" else w.jump()
        start = env.mono[0]
        for elapsed in times:
            env.mono[0] = start + elapsed
            w.advance_to(env.mono[0])
            alpha = pixels(w)[:, :, 3]
            ys, xs = np.where(alpha > 0)
            assert ys.min() > 0 and ys.max() < alpha.shape[0] - 1
            assert xs.min() > 0 and xs.max() < alpha.shape[1] - 1
            assert all(w.mask().contains(QPoint(int(x), int(y))) for x, y in zip(xs, ys))
            assert not w.mask().contains(QPoint(0, 0))


def test_mouse_press_interrupts_jump_without_a_delayed_landing(env):
    w = env.win
    env.ctl.select_expression("working")
    w.jump()
    env.advance(JUMP_CROUCH_DURATION + JUMP_AIR_DURATION / 2)
    assert w.displayed_sprite == "jump_3"
    QTest.mousePress(w, Qt.LeftButton, Qt.NoModifier, BODY)
    assert not w.motion_active and w._jump_offset == 0 and w.displayed_sprite == "working"
    env.advance(1)
    assert w.frame.sy == pytest.approx(working_breath(JUMP_CROUCH_DURATION + JUMP_AIR_DURATION / 2 + 1), abs=.001)
    assert w.displayed_sprite == "working"
    QTest.mouseRelease(w, Qt.LeftButton, Qt.NoModifier, BODY)


def test_snapshot_cli_exposes_turn_and_jump_sequence_stages(qapp, tmp_path):
    from shion.__main__ import main
    frames = []
    for motion, elapsed in (("--turn", "0.04"), ("--turn", "0.14"), ("--jump", "0.10"), ("--jump", "0.35"),
                            ("--drag", "0"), ("--drag", "0.11")):
        out = tmp_path / f"{motion[2:]}-{elapsed}.png"
        assert main(["--snapshot", str(out), motion, "--at", elapsed]) == 0
        img = QImage(str(out)).convertToFormat(QImage.Format_RGBA8888)
        frames.append(bytes(img.constBits()))
    assert len(set(frames)) == 6


def test_snapshot_bubble_does_not_paint_over_jump_at_apex(qapp, tmp_path):
    from shion.app import snapshot
    from shion.bubble import GAP, BubbleWindow
    from shion.pet_window import MARGIN_TOP

    plain, combined = tmp_path / "jump.png", tmp_path / "jump-bubble.png"
    assert snapshot(str(plain), jump=True, at=0.35) == 0
    assert snapshot(str(combined), jump=True, at=0.35, bubble="Hello") == 0
    def rgba(path):
        img = QImage(str(path)).convertToFormat(QImage.Format_RGBA8888)
        return np.frombuffer(img.constBits(), dtype=np.uint8).reshape(
            img.height(), img.bytesPerLine() // 4, 4)[:, :img.width()].copy()
    bubble = BubbleWindow(autostart=False)
    try:
        bubble.say("Hello")
        source, result = rgba(plain), rgba(combined)
        py = max(0, bubble.height() + GAP - (MARGIN_TOP - round(JUMP_HEIGHT)))
        px = (result.shape[1] - source.shape[1]) // 2
        ys, xs = np.where(source[:, :, 3] > 0)
        assert np.array_equal(source[ys, xs], result[ys + py, xs + px])
    finally:
        bubble.close()
