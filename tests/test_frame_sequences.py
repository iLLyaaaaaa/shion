"""帧序列、缺图回退、脚底锚点及遮罩的集成测试。"""
import math
import shutil

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest

from shion import behavior
from shion.animator import SQUASH
from shion.behavior import (
    JUMP_AIR_DURATION, JUMP_CROUCH_DURATION, JUMP_DURATION, JUMP_HEIGHT,
    LEGACY_JUMP_DURATION, LEGACY_JUMP_HEIGHT, WALK_BOB_HEIGHT, WALK_FRAME_SECONDS,
)
from shion.pet_window import PetWindow, SEQUENCES, SPRITE_DIR, STATES
from tests.test_controller import BODY, env, qapp
from tests.test_feedback_ui import pixels, pixmap_pixels


@pytest.mark.parametrize("cross", [False, True])
def test_walk_loops_all_four_frames_without_restarting_on_controller_sync(env, cross):
    env.win.place_default()
    env.win.walk(cross=cross)
    for i in range(9):
        if i:
            env.advance(WALK_FRAME_SECONDS)
        assert env.win.displayed_sprite == f"walk_{i % 4 + 1}"
    env.ctl.handle_event("stop")
    assert env.win.sprite_name == "done" and env.win.displayed_sprite.startswith("walk_")
    env.win.stop_motion()
    assert env.win.displayed_sprite == "done"


def test_frame_rate_and_bob_follow_walk_speed(env, monkeypatch):
    monkeypatch.setattr(behavior, "WALK_SPEED", 160)
    monkeypatch.setattr(env.win, "_screen_avail", lambda *_: QRect(0, 0, 1920, 1040))
    env.win.place_on((0, 0, 1920, 1040), 200)
    start = env.win.x()
    env.win.walk(cross=True)
    assert env.win.displayed_sprite == "walk_1" and env.win._jump_offset == 0
    env.advance(WALK_FRAME_SECONDS / 2)
    assert env.win.displayed_sprite == "walk_2"
    assert abs(env.win.x() - start) == pytest.approx(160 * 0.07, abs=0.5)
    assert env.win._jump_offset == pytest.approx(WALK_BOB_HEIGHT)
    env.advance(WALK_FRAME_SECONDS / 2)
    assert env.win.displayed_sprite == "walk_3"
    assert env.win._jump_offset == pytest.approx(0, abs=1e-9)


def test_walk_source_is_right_facing_and_left_is_pixel_mirrored(env, monkeypatch):
    w = env.win
    monkeypatch.setattr(w, "_screen_avail", lambda *_: QRect(0, 0, 1920, 1040))
    for x, direction in ((200, 1), (1500, -1)):
        w.place_on((0, 0, 1920, 1040), x)
        w.walk(cross=True)
        assert w.facing == direction
        for name in SEQUENCES["walk"]:
            assert np.array_equal(pixmap_pixels(w._pixmaps[name])[:, ::-1],
                                  pixmap_pixels(w._mirrored_pixmaps[name]))
        w.stop_motion()


@pytest.mark.parametrize("automatic", [False, True])
def test_jump_crouches_flies_40px_then_lands_with_squash_and_rebound(env, automatic):
    w = env.win
    w.set_state("working", animate=False)
    original = pixels(w)
    pos = w.pos()
    w.jump(automatic=automatic)
    assert w.displayed_sprite == "jump_1" and w._jump_offset == 0
    assert w.idle_motion_active == automatic
    for elapsed, sprite, height in (
        (0.149, "jump_1", 0), (JUMP_CROUCH_DURATION, "jump_2", 0),
        (JUMP_CROUCH_DURATION + JUMP_AIR_DURATION / 2, "jump_2", JUMP_HEIGHT),
        (JUMP_DURATION, "working", 0),
    ):
        env.mono[0] = 100 + elapsed
        w.advance_to(env.mono[0])
        assert w.displayed_sprite == sprite
        assert w._jump_offset == pytest.approx(height, abs=1e-8)
        assert w.pos() == pos
    land = SQUASH["land"][0]
    w.advance_to(100 + JUMP_DURATION + land * 0.3)
    assert w.frame.sy == pytest.approx(SQUASH["land"][1], abs=0.001)
    w.advance_to(100 + JUMP_DURATION + land * 0.8)
    assert w.frame.sy > 1
    w.advance_to(100 + JUMP_DURATION + land + 0.01)
    assert not w.motion_active and np.array_equal(pixels(w), original)


@pytest.mark.parametrize("action,elapsed", [("walk", 0.47), ("jump", 0.35), ("jump", 0.625), ("jump", 1.0)])
def test_motion_does_not_depend_on_dropped_frames(qapp, action, elapsed):
    windows = [PetWindow(clock=lambda: 100.0, autostart=False) for _ in range(2)]
    try:
        for w in windows:
            w.set_state("working", animate=False)
            w.place_default()
            w.walk(cross=True) if action == "walk" else w.jump()
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


@pytest.mark.parametrize("missing", ["walk_2", "jump_1", "jump_2"])
@pytest.mark.parametrize("problem", ["absent", "corrupt", "wrong_canvas"])
def test_optional_group_falls_back_as_a_whole(qapp, tmp_path, monkeypatch, missing, problem):
    import shion.pet_window as module
    for name in STATES + list(SEQUENCES["walk"]) + list(SEQUENCES["jump"]):
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
        assert ("jump" if group == "walk" else "walk") in w._sequences
        w.set_state("working", animate=False)
        if group == "jump":
            w.jump()
            w.advance_to(100 + LEGACY_JUMP_DURATION / 2)
            assert w.displayed_sprite == "working"
            assert w._jump_offset == pytest.approx(LEGACY_JUMP_HEIGHT)
            w.advance_to(100 + LEGACY_JUMP_DURATION)
            assert not w.motion_active and w._jump_offset == 0
        else:
            w.place_default()
            w.walk(cross=True)
            w.advance_to(100.1)
            assert w.displayed_sprite == "working"
            assert w._jump_offset == pytest.approx(
                behavior.WALK_HOP_HEIGHT * abs(math.sin(math.pi * 0.1 / behavior.WALK_HOP_PERIOD)))
    finally:
        w.close()


@pytest.mark.parametrize("height", [160, 200, 260, 320])
@pytest.mark.parametrize("direction", [1, -1])
def test_motion_pixels_are_not_clipped_and_masks_cover_visible_pixels(env, height, direction):
    w = env.win
    w.set_height(height)
    w.set_state("working", animate=False)
    w.place_default()
    for action, times in (("walk", [0, 0.14, 0.28, 0.42]), ("jump", [0, 0.15, 0.35, 0.625])):
        w.walk(cross=True) if action == "walk" else w.jump()
        start = env.mono[0]
        for elapsed in times:
            env.mono[0] = start + elapsed
            w.advance_to(env.mono[0])
            w.face(direction)
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
    assert w.displayed_sprite == "jump_2"
    QTest.mousePress(w, Qt.LeftButton, Qt.NoModifier, BODY)
    assert not w.motion_active and w._jump_offset == 0 and w.displayed_sprite == "working"
    env.advance(1)
    assert w.frame.sy == 1 and w.displayed_sprite == "working"
    QTest.mouseRelease(w, Qt.LeftButton, Qt.NoModifier, BODY)


def test_snapshot_cli_exposes_walk_and_jump_sequence_stages(qapp, tmp_path):
    from shion.__main__ import main
    frames = []
    for motion, elapsed in (("--walk", "0"), ("--walk", "0.14"), ("--jump", "0"), ("--jump", "0.35")):
        out = tmp_path / f"{motion[2:]}-{elapsed}.png"
        assert main(["--snapshot", str(out), motion, "--at", elapsed]) == 0
        img = QImage(str(out)).convertToFormat(QImage.Format_RGBA8888)
        frames.append(bytes(img.constBits()))
    assert len(set(frames)) == 4


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
