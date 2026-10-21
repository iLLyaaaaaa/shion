"""床/桌时间线、宽画布、慢放/甩出、位置恢复的回归。"""
import json
import random
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest

from shion import behavior as b
from shion import state as S
from shion.pet_window import MARGIN_BOTTOM, MARGIN_TOP, MARGIN_X, SPRITE_DIR, STATES, PetWindow
from tests.test_controller import Env, env, find_action, qapp
from tests.test_feedback_ui import move_global
from tests.test_pet_window import alpha_of


@pytest.mark.parametrize("elapsed,expected", [(0, 1), (.899, 1), (.9, 2), (1.799, 2), (1.8, 1), (90.9, 2)])
def test_bed_breathing_boundaries(elapsed, expected):
    p = b.PropPlayback(random.Random(2))
    p.reset(100)
    assert p.sprite("bed", 100 + elapsed) == f"bed_{expected}"


def test_desk_blinks_sighs_and_skips_missed_frames():
    p = b.PropPlayback(random.Random(2))
    p.reset(100)
    assert 101.5 <= p.blink <= 103.5 and 110 <= p.sigh <= 120
    blink = p.blink
    assert p.sprite("desk", blink - .001) == "desk_1"
    assert p.sprite("desk", blink) == "desk_2"
    assert p.sprite("desk", blink + .15) == "desk_1"
    sigh = p.sigh
    assert p.sprite("desk", sigh) == "desk_3"
    assert p.sprite("desk", sigh + 1.2) == "desk_1"
    a, c = b.PropPlayback(random.Random(8)), b.PropPlayback(random.Random(8))
    a.reset(100)
    c.reset(100)
    for t in np.arange(100, 160, .05):
        a.sprite("desk", t)
    assert a.sprite("desk", 160) == c.sprite("desk", 160)
    assert (a.blink, a.sigh, a.active) == (c.blink, c.sigh, c.active)


@pytest.mark.parametrize("height", [160, 200, 260, 320])
def test_wide_transition_preserves_feet_aspect_and_mask(env, height):
    w = env.win
    w.set_height(height)
    w.move(200, 100)
    anchor = (w.x() + w.width() / 2, w.y() + w.height() - MARGIN_BOTTOM)
    w.set_state("bed")
    assert w.sprite_size == (round(height * 640 / 512), height)
    for dt in (0, .06, .1, .9):
        env.mono[0] += dt
        w.advance_to(env.mono[0])
        assert w.x() + w.width() / 2 == pytest.approx(anchor[0], abs=.5)
        assert w.y() + w.height() - MARGIN_BOTTOM == anchor[1]
        a = alpha_of(w)
        ys, xs = np.where(a > 64)
        assert len(xs) and all(w.mask().contains(QPoint(int(x), int(y))) for x, y in zip(xs, ys))
        assert not w.mask().contains(QPoint(0, 0))
        assert not a[:, 0].any() and not a[:, -1].any()
    w.set_state("idle")
    env.mono[0] += .15
    w.advance_to(env.mono[0])
    assert w.sprite_size[0] == round(height * 448 / 512)
    assert w.x() + w.width() / 2 == pytest.approx(anchor[0], abs=1)


def test_wide_image_is_not_stretched_and_opaque_blend_stays_opaque(env):
    w = env.win
    for name, color in (("idle", "red"), ("bed_1", "blue")):
        w._pixmaps[name].fill(color)
    w.set_state("bed")
    env.mono[0] += .06
    w.advance_to(env.mono[0])
    image = w.render_frame()
    center = image.pixelColor(w.width() // 2, MARGIN_TOP + 100)
    edge = image.pixelColor(MARGIN_X + 5, MARGIN_TOP + 100)
    assert center.alpha() == 255 and center.red() > 0 and center.blue() > 0
    assert edge.red() == 0 and 0 < edge.alpha() < 255


def test_grabbing_wide_canvas_keeps_cursor_offset_when_drag_sprite_narrows(env):
    w = env.win
    w.move(200, 100)
    env.ctl.do_action("bed")
    env.advance(.2)
    center = w.x() + w.width() / 2
    point = QPoint(MARGIN_X + 20, MARGIN_TOP + 170)
    QTest.mousePress(w, Qt.LeftButton, Qt.NoModifier, point)
    gp = w.mapToGlobal(point)
    move_global(w, gp + QPoint(20, -20))
    assert w.is_dragging
    assert w.x() + w.width() / 2 == pytest.approx(center + 20, abs=1)
    QTest.mouseRelease(w, Qt.LeftButton, Qt.NoModifier, w.mapFromGlobal(gp + QPoint(20, -20)))


@pytest.mark.parametrize("action", ["bed", "desk"])
def test_menu_props_touch_restores_and_does_not_gain_affection(env, action):
    menu = env.ctl.build_menu()
    find_action(find_action(menu, "动作").menu(), env.ctl.lines.ui("action_" + action)).trigger()
    assert env.win.sprite_name == action
    assert not env.state.can_idle(env.now)
    assert env.data.affection == 0 and env.data.stats["pats"] == 0
    env.win.clicked.emit()
    assert env.win.sprite_name == "idle"
    if action == "bed":
        # 让原菜单台词自然结束，再验唤醒台词；状态始终立即唤醒。
        assert not env.state.sleep_in_bed(env.now)


def test_goodnight_and_night_use_bed_day_idle_uses_original_sleep(env):
    env.ctl.choose_dialogue("talks", "goodnight")
    assert env.win.sprite_name == "bed"
    env.win.clicked.emit()
    env.advance(901)
    assert env.win.sprite_name == "sleep"
    env.now = datetime(2026, 10, 20, 1)
    env.ctl.sync()
    assert env.win.sprite_name == "bed"
    env.data.last_attended = env.now  # 此处只验证夜间唤醒；久别回归台词另有专项。
    env.ctl._speech.dismiss()
    env.win.clicked.emit()
    assert env.win.sprite_name != "bed"
    assert env.said[-1] in env.ctl.lines._lines["wake"]


@pytest.mark.parametrize("roll,expected", [(0, "desk"), (.99, "neglect1")])
def test_neglect_decides_once_until_touched_and_does_not_reset_attention(env, monkeypatch, roll, expected):
    env.data.last_attended = env.now - timedelta(minutes=31)
    original = env.data.last_attended
    calls = []
    monkeypatch.setattr(env.ctl._rng, "random", lambda: calls.append(1) or roll)
    env.ctl.sync()
    assert env.win.sprite_name == expected
    for _ in range(4):
        env.ctl.sync()
    assert len(calls) == 1 and env.data.last_attended == original
    env.win.clicked.emit()
    assert env.win.sprite_name == "idle"


@pytest.mark.parametrize("speed", [b.RELEASE_FAST_SPEED - 1, b.RELEASE_FAST_SPEED, b.RELEASE_FAST_SPEED + 1])
def test_release_speed_boundary_and_stale_movement(speed):
    v = b.ReleaseVelocity()
    v.feed(0, 0, 0)
    assert v.speed(.1, speed * .1, 0) == pytest.approx(speed)
    assert v.speed(1, speed * .1, 0) == 0


def drag_release(e, delta, seconds, hold=0):
    w = e.win
    w.move(200, 100)
    point = QPoint(MARGIN_X + 20, MARGIN_TOP + 170)
    QTest.mousePress(w, Qt.LeftButton, Qt.NoModifier, point)
    gp = w.mapToGlobal(point)
    e.mono[0] += seconds
    move_global(w, gp + delta)
    assert w.is_dragging and w.displayed_sprite.startswith("drag_")
    e.mono[0] += hold
    QTest.mouseRelease(w, Qt.LeftButton, Qt.NoModifier, w.mapFromGlobal(gp + delta))


@pytest.mark.parametrize("fast,legacy,hold,fall", [(False, False, 0, False), (True, False, 0, True),
    (True, False, 1, False), (False, True, 0, True)])
def test_slow_drop_stays_fast_drop_falls_and_switch_restores_legacy(env, fast, legacy, hold, fall):
    env.ctl.set_release_to_taskbar(legacy)
    drag_release(env, QPoint(50, -50), .05 if fast else 1, hold)
    assert env.win.is_falling == fall
    if fall:
        env.advance(3)
        assert not env.win.is_falling
        assert not env.win.is_floating
    else:
        assert env.win.is_floating and env.win._drag_playback is None
        assert not env.state._dragging
        y = env.win.y()
        env.advance(3)
        assert env.win.y() == y
        assert env.data.window["y"] == y


def test_release_clamps_all_edges(env):
    w = env.win
    avail = w._screen_avail()
    for x, y in ((-5000, -5000), (5000, 5000)):
        w.move(x, y)
        w.clamp_position(avail)
        bx, by, bw, bh = w.body_rect()
        assert bx >= avail.left() and by >= avail.top()
        assert bx + bw <= avail.right() + 1 and by + bh <= avail.bottom() + 1


def test_floating_position_size_and_switch_survive_restart(env, tmp_path, qapp):
    env.win.move(200, 100)
    env.ctl.set_release_to_taskbar(True)
    env.ctl.save_position()
    anchor = env.win.x() + env.win.width() / 2, env.win.y() + env.win.height() - MARGIN_BOTTOM
    env.ctl.set_size(260)
    assert (env.win.x() + env.win.width() / 2, env.win.y() + env.win.height() - MARGIN_BOTTOM) == pytest.approx(anchor, abs=.5)
    env.scheduler.flush()
    other = Env(tmp_path)
    try:
        other.ctl.restore_position()
        assert other.win.is_floating and other.win.release_to_taskbar
        assert other.win.pos() == env.win.pos()
    finally:
        other.close()


def test_bed_position_saved_as_normal_canvas_center(env, tmp_path):
    env.win.move(200, 100)
    anchor = env.win.x() + env.win.width() / 2
    env.ctl.do_action("bed")
    env.ctl.save_position()
    env.scheduler.flush()
    other = Env(tmp_path)
    try:
        other.ctl.restore_position()
        assert other.win.x() + other.win.width() / 2 == pytest.approx(anchor, abs=.5)
        assert other.win.y() == 100
    finally:
        other.close()


@pytest.mark.parametrize("raw,expected", [({}, False), ({"release_to_taskbar": "yes"}, False), ({"release_to_taskbar": True}, True)])
def test_option_defaults_and_roundtrip(raw, expected):
    data = S.SaveData.from_dict(raw)
    assert data.release_to_taskbar is expected
    assert S.SaveData.from_dict(data.to_dict()).release_to_taskbar is expected


@pytest.mark.parametrize("lang", ["zh", "en", "ja"])
def test_new_menu_and_lines_are_native_and_have_no_model_name(env, lang):
    env.ctl.set_language(lang)
    raw = json.loads((Path("assets/lines") / f"{lang}.json").read_text(encoding="utf-8"))
    for key in ("action_bed", "action_desk", "menu_release_to_taskbar"):
        assert raw["ui"][key] and "claude" not in raw["ui"][key].lower()
    for key in ("bedtime", "desk_rest"):
        assert len(raw["lines"][key]) >= 3
        assert all("claude" not in line.lower() for line in raw["lines"][key])


@pytest.mark.parametrize("group,bad", [("bed", "missing"), ("bed", "canvas"), ("desk", "broken")])
def test_bad_prop_group_falls_back_without_affecting_other_group(qapp, tmp_path, monkeypatch, group, bad):
    from PySide6.QtGui import QImage
    import shion.pet_window as module
    for name in STATES + ["bed_1", "bed_2", "desk_1", "desk_2", "desk_3"]:
        shutil.copyfile(SPRITE_DIR / f"{name}.png", tmp_path / f"{name}.png")
    path = tmp_path / f"{group}_2.png"
    if bad == "missing":
        path.unlink()
    elif bad == "broken":
        path.write_bytes(b"not an image")
    else:
        image = QImage(448, 510, QImage.Format_ARGB32)
        image.fill(Qt.red)
        image.save(str(path))
    monkeypatch.setattr(module, "SPRITE_DIR", tmp_path)
    w = PetWindow(clock=lambda: 100, autostart=False)
    try:
        w.set_state(group, animate=False)
        assert w.displayed_sprite == {"bed": "sleep", "desk": "neglect1"}[group]
        other = "bed" if group == "desk" else "desk"
        assert other in w._sequences
    finally:
        w.close()


def test_desk_yields_to_work_and_fixed_state_and_wakes_on_gesture(env):
    env.ctl.do_action("desk")
    env.win.gesture.emit("belly")
    assert env.win.sprite_name == "idle"
    env.ctl.do_action("desk")
    env.ctl.handle_event("working")
    assert env.win.sprite_name == "working"
    env.ctl.do_action("desk")
    env.data.fixed_expression = "proud"
    env.ctl.sync()
    assert env.win.sprite_name == "proud"


def test_other_action_sequences_can_also_have_wider_canvas(qapp, tmp_path, monkeypatch):
    from PySide6.QtGui import QImage
    import shion.pet_window as module
    for name in STATES:
        shutil.copyfile(SPRITE_DIR / f"{name}.png", tmp_path / f"{name}.png")
    image = QImage(700, 512, QImage.Format_ARGB32)
    image.fill(Qt.red)
    for i in range(1, 5):
        image.save(str(tmp_path / f"jump_{i}.png"))
    monkeypatch.setattr(module, "SPRITE_DIR", tmp_path)
    w = PetWindow(clock=lambda: 100, autostart=False)
    try:
        w.move(200, 100)
        center = w.x() + w.width() / 2
        w.jump()
        for elapsed in (0, .05, .1, b.JUMP_DURATION, b.JUMP_DURATION + .05):
            w.advance_to(100 + elapsed)
            assert w.sprite_size[0] == round(700 * 200 / 512)
            assert w.x() + w.width() / 2 == pytest.approx(center, abs=.5)
        w.advance_to(100 + b.JUMP_DURATION + module.ACTION_FADE_SECONDS)
        assert w.sprite_size[0] == w.normal_width
        assert w.x() + w.width() / 2 == pytest.approx(center, abs=1)
    finally:
        w.close()
