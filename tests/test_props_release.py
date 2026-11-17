"""床/桌时间线、宽画布、慢放/甩出、位置恢复的回归。"""
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from shion import behavior as b
from shion import state as S
from shion.pet_window import MARGIN_BOTTOM
from tests.test_controller import Env, env, find_action, qapp
from tests.test_feedback_ui import move_global
from tests.test_v3_gestures import find


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
    """V3 里只有“捏着脸颊往上提”会真的拖动窗口：从脸颊处按下，再按 delta 移动。"""
    w = e.win
    w.move(200, 100)
    point = find(w, "cheek")
    QTest.mousePress(w, Qt.LeftButton, Qt.NoModifier, point)
    gp = w.mapToGlobal(point)
    e.mono[0] += seconds
    move_global(w, gp + delta)
    assert w.is_dragging and w.lifting
    e.mono[0] += hold
    QTest.mouseRelease(w, Qt.LeftButton, Qt.NoModifier, w.mapFromGlobal(gp + delta))


@pytest.mark.parametrize("fast,legacy,hold,fall", [(False, False, 0, False), (True, False, 0, True),
    (True, False, 1, False), (False, True, 0, True)])
def test_slow_drop_stays_fast_drop_falls_and_switch_restores_legacy(env, fast, legacy, hold, fall):
    env.ctl.set_release_to_taskbar(legacy)
    drag_release(env, QPoint(20, -60), .05 if fast else 1, hold)
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
