"""真实 Qt 手势、时间边界和三语仲裁；不依赖用户鼠标或真实等待。"""
import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from shion import behavior as b
from shion.pet_window import MARGIN_TOP, MARGIN_X
from shion.speech import Priority
from tests.test_controller import env, qapp
from tests.test_feedback_ui import move_global, pixels


def point(w, x=.5, y=.48):
    sw, sh = w.sprite_size
    return QPoint(MARGIN_X + round(sw * x), MARGIN_TOP + round(sh * y))


def press(w, y=.48):
    pos = point(w, y=y)
    QTest.mousePress(w, Qt.LeftButton, Qt.NoModifier, pos)
    return w.mapToGlobal(pos)


def release(w, global_pos):
    QTest.mouseRelease(w, Qt.LeftButton, Qt.NoModifier, w.mapFromGlobal(global_pos))


def belly_click(e):
    QTest.mouseClick(e.win, Qt.LeftButton, Qt.NoModifier, point(e.win, y=.69))


@pytest.mark.parametrize("automatic", [False, True])
def test_turn_displays_all_eight_frames_once_and_restores_idle(env, automatic):
    w = env.win
    original = w.pos()
    w.turn(automatic=automatic)
    for i in range(8):
        if i:
            env.advance(b.TURN_FRAME_SECONDS)
        assert w.displayed_sprite == f"turn_{i + 1}"
        assert w.idle_motion_active == automatic
        assert w.pos() == original and w._jump_offset == 0
    env.advance(b.TURN_FRAME_SECONDS)
    assert w.displayed_sprite == "idle" and not w.motion_active


@pytest.mark.parametrize("action", ["turn", "face"])
def test_idle_scheduler_uses_same_turn_and_side_pose(env, monkeypatch, action):
    monkeypatch.setattr(env.ctl._idle, "step", lambda *args: action)
    env.ctl.tick()
    assert env.win.idle_motion_active
    if action == "turn":
        assert env.win.displayed_sprite == "turn_1"
    else:
        assert env.win.displayed_sprite in {"turn_2", "turn_8"}


@pytest.mark.parametrize("direction,sprite", [(1, "turn_2"), (-1, "turn_8")])
def test_side_pose_times_out_and_never_builds_mirror_cache(env, direction, sprite):
    w = env.win
    pos = w.pos()
    w.face(direction)
    assert w.displayed_sprite == sprite and not hasattr(w, "_mirrored_pixmaps")
    env.advance(b.FACE_SECONDS - .001)
    assert w.displayed_sprite == sprite
    env.advance(.001)
    assert w.displayed_sprite == "idle" and w.pos() == pos
    assert "walk" not in w._sequences
    assert not any(name.startswith("walk_") for name in w._pixmaps)


@pytest.mark.parametrize("action", ["turn", "face"])
def test_press_interrupts_pose_and_work_interrupts_only_automatic_pose(env, action):
    start = (lambda automatic: env.win.turn(automatic=automatic)) if action == "turn" else (
        lambda automatic: env.win.face(1, automatic=automatic))
    start(True)
    env.ctl.handle_event("working")
    assert not env.win.motion_active
    start(False)
    env.ctl.sync()
    assert env.win.motion_active
    gp = press(env.win, .9)
    assert not env.win.motion_active
    release(env.win, gp)


@pytest.mark.parametrize("height", [160, 200, 260, 320])
def test_zones_follow_idle_canvas_and_exclude_margins(env, height):
    w = env.win
    w.set_height(height)
    for y, zone in ((.20, "head"), (.37, "head"), (.39, "cheek"), (.55, "cheek"),
                    (.57, "body"), (.61, "belly"), (.77, "belly"), (.80, "body")):
        assert w._hit_zone(point(w, y=y)) == zone
    assert w._hit_zone(point(w, x=.2, y=.69)) == "body"
    assert w._hit_zone(QPoint(0, 0)) == "outside"
    assert w._hit_zone(QPoint(MARGIN_X - 1, MARGIN_TOP + 30)) == "outside"


@pytest.mark.parametrize("dx,name", [(20, "cheek_1"), (-20, "cheek_2")])
def test_cheek_pull_and_release_use_direction_frames_and_angry_line(env, dx, name):
    w = env.win
    gp = press(w)
    pos = w.pos()
    move_global(w, gp + QPoint(dx, 0))
    assert w.displayed_sprite == name and not w.is_dragging and w.pos() == pos
    assert env.said[-1] in env.ctl.lines._lines["cheek_pull"]
    release(w, gp + QPoint(dx, 0))
    assert w.displayed_sprite == "cheek_3"
    assert env.said[-1] in env.ctl.lines._lines["cheek_release"]
    env.advance(b.CHEEK_RELEASE_SECONDS - .001)
    assert w.displayed_sprite == "cheek_3"
    env.advance(.001)
    assert w.displayed_sprite == "idle"
    assert env.data.affection == env.data.stats["pats"] == env.state._poke_count == 0


def test_cheek_direction_can_reverse_without_restarting_dialogue(env):
    gp = press(env.win)
    move_global(env.win, gp + QPoint(30, 0))
    move_global(env.win, gp + QPoint(-30, 0))
    assert env.win.displayed_sprite == "cheek_2" and len(env.said) == 1
    release(env.win, gp + QPoint(-30, 0))


@pytest.mark.parametrize("delta", [QPoint(81, 0), QPoint(-81, 0), QPoint(0, -81)])
def test_cheek_becomes_lift_after_80px_without_release_anger(env, delta):
    env.win.release_to_taskbar = True  # 验证菜单开关开启后的原重力行为
    w = env.win
    w.place_default()
    gp = press(w)
    move_global(w, gp + QPoint(80, 0))
    assert w.displayed_sprite == "cheek_1" and not w.is_dragging
    move_global(w, gp + delta)
    assert w.is_dragging and w.displayed_sprite.startswith("drag_")
    release(w, gp + delta)
    assert not w.is_dragging and w.displayed_sprite != "cheek_3"
    if delta.y() < 0:
        assert w.is_falling


def test_belly_first_two_clicks_are_silent_and_never_poke_or_show_double_status(env):
    env.win.clicked.emit()  # 先前的身体戳不会与肚子点击混算
    assert env.state._poke_count == 1
    env.said.clear()
    belly_click(env)
    env.advance(.5)
    belly_click(env)
    assert not env.win.motion_active and not env.said
    assert env.state._poke_count == 0
    assert not env.ctl._status_timer.isActive()


@pytest.mark.parametrize("last,active", [(1.5, True), (1.501, False)])
def test_belly_three_clicks_use_sliding_inclusive_1500ms_window(env, last, active):
    belly_click(env)
    env.advance(.7)
    belly_click(env)
    env.advance(last - .7)
    belly_click(env)
    assert (env.win._tickle_start is not None) == active
    assert env.state._poke_count == 0
    if active:
        assert env.win.displayed_sprite == "tickle_1"
        assert env.said[-1] in env.ctl.lines._lines["tickle"]


def test_three_clicks_after_long_gap_do_not_reuse_old_clicks(env):
    belly_click(env)
    env.advance(2)
    belly_click(env)
    env.advance(.2)
    belly_click(env)
    assert env.win._tickle_start is None
    belly_click(env)
    assert env.win._tickle_start is not None


def test_held_belly_rubbing_loops_all_frames_twists_and_stops_one_second_after_motion(env):
    w = env.win
    gp = press(w, .69)
    for dx in (12, -12, 12):
        move_global(w, gp + QPoint(dx, 0))
        env.advance(.1)
    assert w._tickle_start is not None and not w.is_dragging
    start = w._tickle_start
    seen, angles = set(), set()
    for i in range(12):
        move_global(w, gp + QPoint(-12 if i % 2 else 12, 0))
        env.advance(.11)
        seen.add(w.displayed_sprite)
        angles.add(w.frame.angle)
    assert seen == {"tickle_1", "tickle_2", "tickle_3"}
    assert min(angles) < 0 < max(angles)
    assert w._tickle_start == start
    last = w._tickle_last
    release(w, gp)
    env.advance(last + b.TICKLE_STOP_SECONDS - env.mono[0] - .001)
    assert w._tickle_start is not None
    env.advance(.001)
    assert w._tickle_start is None and w.displayed_sprite == "idle"
    assert env.said[-1] in env.ctl.lines._lines["tickle_end"]
    count = len(env.said)
    env.advance(1)
    assert len(env.said) == count


def test_holding_still_does_not_count_as_continuing_to_tickle(env):
    for _ in range(3):
        belly_click(env)
    gp = press(env.win, .69)
    env.advance(1)
    assert env.win._tickle_start is None
    release(env.win, gp)


def test_small_effective_motion_can_continue_an_already_active_tickle(env):
    for _ in range(3):
        belly_click(env)
    gp = press(env.win, .69)
    for i in range(12):
        env.advance(.2)
        move_global(env.win, gp + QPoint(2 if i % 2 else -2, 0))
    assert env.win._tickle_start == 100 and not env.win.is_dragging
    release(env.win, gp)


def test_continued_tickle_repeats_laughter_without_restarting_frames(env):
    gp = press(env.win, .69)
    for dx in (12, -12, 12):
        move_global(env.win, gp + QPoint(dx, 0))
    for i in range(50):
        env.advance(.1)
        move_global(env.win, gp + QPoint(12 if i % 2 else -12, 0))
    assert env.win._tickle_start == 100
    assert len(env.said) == 2
    assert all(s in env.ctl.lines._lines["tickle"] for s in env.said)
    release(env.win, gp)


def test_belly_long_drag_lifts_and_cancels_laughter_without_poke(env):
    env.win.release_to_taskbar = True  # 验证菜单开关开启后的原重力行为
    w = env.win
    w.place_default()
    gp = press(w, .69)
    for dx in (12, -12, 12):
        move_global(w, gp + QPoint(dx, 0))
    move_global(w, gp + QPoint(40, 0))
    assert not w.is_dragging
    move_global(w, gp + QPoint(41, -100))
    assert w.is_dragging and w._tickle_start is None
    release(w, gp + QPoint(41, -100))
    assert w.is_falling and env.state._poke_count == 0


def test_small_belly_jitter_and_one_way_motion_do_not_trigger_tickle(env):
    gp = press(env.win, .69)
    for dx in (1, -1, 2, -2, 3, -3, 5, -3, 10, 20, 30):
        move_global(env.win, gp + QPoint(dx, 0))
    assert env.win._tickle_start is None and not env.win.is_dragging
    release(env.win, gp)
    assert env.state._poke_count == 0


@pytest.mark.parametrize("kind", ["cheek", "tickle"])
def test_fixed_expression_restores_after_interaction_without_affection_or_feedback(env, kind):
    env.ctl.select_expression("proud")
    env.ctl.fix_expression(True)
    if kind == "cheek":
        gp = press(env.win)
        move_global(env.win, gp + QPoint(20, 0))
        release(env.win, gp + QPoint(20, 0))
    else:
        for _ in range(3):
            belly_click(env)
    env.advance(2)
    assert env.win.displayed_sprite == "proud"
    assert env.data.fixed_expression == "proud"
    assert env.data.affection == env.data.stats["pats"] == 0
    assert env.data.feedback_queue == []


@pytest.mark.parametrize("muted", [True, False])
@pytest.mark.parametrize("key", ["cheek_pull", "cheek_release", "tickle", "tickle_end"])
def test_gesture_dialogue_respects_mute_and_high_priority_work_reminder(env, muted, key):
    env.ctl.set_muted(muted)
    env.ctl.say("Important", priority=Priority.HIGH, category="plan_ready")
    before = list(env.said)
    env.win.gesture.emit(key)
    assert env.said == before


@pytest.mark.parametrize("height", [160, 200, 260, 320])
def test_cheek_and_tickle_masks_cover_visible_pixels_at_every_size(env, height):
    w = env.win
    w.set_height(height)
    for group in ("cheek", "tickle"):
        for i in range(3):
            if group == "cheek":
                w._pose = f"cheek_{i + 1}"
                w._pose_until = 200
            else:
                w._pose = None
                w._feed_tickle(100)
                w._tickle_last = 200
            w.advance_to(100 + i * .11)
            alpha = pixels(w)[:, :, 3]
            ys, xs = np.where(alpha > 0)
            assert xs.min() > 0 and xs.max() < w.width() - 1
            assert ys.min() > 0 and ys.max() < w.height() - 1
            assert all(w.mask().contains(QPoint(int(x), int(y))) for x, y in zip(xs, ys))


def test_rub_requires_two_real_reversals_within_window():
    s = b.TickleGesture()
    assert not s.rub(12, 0)
    assert not s.rub(-12, .1)
    assert s.rub(12, 1.6)
    s.begin_rub(0)
    assert not s.rub(12, 0)
    assert not s.rub(-12, .1)
    assert not s.rub(12, 1.601)


def test_belly_double_click_is_consumed_without_status_query(env):
    pos = point(env.win, y=.69)
    belly_click(env)
    QTest.mouseDClick(env.win, Qt.LeftButton, Qt.NoModifier, pos)
    QTest.mouseRelease(env.win, Qt.LeftButton, Qt.NoModifier, pos)
    assert not env.ctl._status_timer.isActive() and not env.said
    belly_click(env)
    assert env.win._tickle_start is not None


@pytest.mark.parametrize("group,count", [("turn", 7), ("turn", 9), ("tickle", 2),
                                         ("tickle", 4), ("cheek", 2), ("cheek", 4)])
def test_new_sequences_reject_incomplete_or_extra_frames(qapp, tmp_path, monkeypatch, group, count):
    import shutil
    from shion import pet_window as module
    for name in module.STATES:
        shutil.copyfile(module.SPRITE_DIR / f"{name}.png", tmp_path / f"{name}.png")
    for i in range(1, count + 1):
        shutil.copyfile(module.SPRITE_DIR / f"{group}_1.png", tmp_path / f"{group}_{i}.png")
    monkeypatch.setattr(module, "SPRITE_DIR", tmp_path)
    w = module.PetWindow(autostart=False)
    try:
        assert group not in w._sequences
        assert not any(n.startswith(group + "_") for n in w._pixmaps)
    finally:
        w.close()


@pytest.mark.parametrize("args", [["--face", "left"], ["--face", "right"], ["--cheek", "left"],
                                  ["--cheek", "right"], ["--cheek", "release"], ["--tickle"]])
def test_snapshot_cli_accepts_new_gesture_previews(qapp, tmp_path, args):
    from shion.__main__ import main
    out = tmp_path / "preview.png"
    assert main(["--snapshot", str(out), *args, "--at", ".22"]) == 0
    assert out.stat().st_size > 1000
