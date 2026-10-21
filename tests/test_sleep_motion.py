"""睡眠 Z、趴桌双眨、工作点头与冷落慢摇的时间线及窗口边界。"""
import math
import random

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter

from shion import animator as A, behavior as B, effects as E
from shion.animator import Animator
from shion.pet_window import MARGIN_BOTTOM
from tests.test_controller import env, qapp


def alpha(image):
    image = image.convertToFormat(QImage.Format_RGBA8888)
    return np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.bytesPerLine() // 4, 4)[:, :image.width(), 3].copy()


def test_z_emission_interval_cap_and_no_catchup():
    z = E.SleepZParticles()
    z.update(0, True)
    assert z.born == [0]
    z.update(.899, True)
    assert z.born == [0]
    z.update(.9, True)
    z.update(1.8, True)
    assert len(z.born) == 3
    for t in np.arange(1.8, 20, .01):
        z.update(float(t), True)
        assert len(z.born) <= 3
    z.update(100, True)
    assert z.born == [100]
    z.update(100, True)
    assert z.born == [100]


def test_z_motion_growth_swing_and_final_third_fade():
    z = E.SleepZParticles()
    z.update(0, True)
    assert z.items(0) == [(0, 0, .5, 0, 1)]
    for t in np.linspace(0, E.Z_LIFETIME - 1e-5, 101):
        x, y, scale, angle, opacity = z.items(float(t))[0]
        assert x >= 0 and y == -x
        assert math.hypot(x, y) <= 40
        assert .5 <= scale <= 1 and abs(angle) <= 8
        assert 0 < opacity <= 1
    assert z.items(.3)[0][3] == pytest.approx(8)
    assert z.items(.9)[0][3] == pytest.approx(-8)
    assert z.items(1.6)[0][-1] == pytest.approx(1)
    assert z.items(2)[0][-1] == pytest.approx(.5)
    assert z.items(2.4) == []
    assert math.hypot(*z.items(2.399)[0][:2]) == pytest.approx(40, abs=.02)
    z.update(.9, True)
    distances = [math.hypot(x, y) for x, y, *_ in z.items(1.8)]
    assert distances[0] - distances[1] == pytest.approx(15)


def test_wake_fades_immediately_without_restarting_on_each_frame():
    z = E.SleepZParticles()
    z.update(0, True)
    z.update(.9, True)
    before = z.items(1)
    z.update(1, False)
    assert z.items(1) == before
    z.update(1.075, False)
    assert len(z.born) == 2
    assert all(item[-1] == pytest.approx(.5) for item in z.items(1.075))
    z.update(1.15, False)
    assert z.born == []
    z.update(2, False)
    assert z.items(2) == []
    z.update(2, True)
    assert z.born == [2] and z.items(2)[0][-1] == 1


def test_wake_during_natural_fade_and_rapid_resleep():
    z = E.SleepZParticles()
    z.update(0, True)
    z.update(2, False)
    assert z.items(2)[0][-1] == pytest.approx(.5)
    assert z.items(2.075)[0][-1] < .25
    z.update(2.08, True)
    assert z.born == [2.08] and z.items(2.08)[0][-1] == 1


@pytest.mark.parametrize("state", ["sleep", "bed"])
@pytest.mark.parametrize("height", [160, 200, 260, 320])
def test_z_window_scales_follows_stays_clickthrough_and_outside_mask(env, state, height):
    w = env.win
    env.ctl.set_always_on_top(False)
    w.set_height(height)
    w.set_state(state, animate=False)
    z = w._sleep_z
    assert z is not None and not z.isVisible()
    assert z.scale == height / 200
    assert z.windowFlags() & Qt.WindowTransparentForInput
    assert z.windowFlags() & Qt.WindowDoesNotAcceptFocus
    assert not z.windowFlags() & Qt.WindowStaysOnTopHint
    assert z.testAttribute(Qt.WA_ShowWithoutActivating)
    w.show()
    assert z.isVisible()
    mask = w.mask()
    before = z.pos()
    w.move(w.pos() + QPoint(23, 17))
    assert z.pos() - before == QPoint(23, 17)
    for t in (.3, .9, 1.8, 2.3):
        env.mono[0] = 100 + t
        w.advance_to(env.mono[0])
        assert w.mask() == w._mask_for(w.frame)  # 只取身体当前帧，不并入 Z
        if state == "sleep":
            assert w.mask() == mask
        image = QImage(z.size(), QImage.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        z.draw(painter, QPointF(E.Z_ORIGIN[0] * z.scale, E.Z_ORIGIN[1] * z.scale))
        painter.end()
        ys, xs = np.where(alpha(image) > 0)
        assert len(xs) and xs.min() > 0 and ys.min() > 0
        assert xs.max() < image.width() - 1 and ys.max() < image.height() - 1
    for on in (True, False, True):
        env.ctl.set_always_on_top(on)
        assert bool(z.windowFlags() & Qt.WindowStaysOnTopHint) == on
        assert z.isVisible()
    w.hide()
    assert not z.isVisible() and not z.particles.born
    w.show()
    assert z.isVisible()
    w.close()
    assert not z.isVisible() and not z.particles.born


@pytest.mark.parametrize("next_state", ["idle", "working", "drag", "desk"])
def test_leaving_sleep_stops_emission_and_fades_even_during_crossfade(env, next_state):
    w = env.win
    w.set_state("sleep", animate=False)
    z = w._sleep_z
    env.mono[0] += .9
    w.advance_to(env.mono[0])
    w.set_state(next_state)
    assert not z.particles.sleeping
    assert z.particles.wake_at == env.mono[0]
    env.mono[0] += E.Z_WAKE_FADE
    w.advance_to(env.mono[0])
    assert not z.particles.born and not z.isVisible()


def test_bed_missing_group_uses_sleep_anchor_and_action_suppresses_z(env):
    w = env.win
    w._sequences.pop("bed")
    w.set_state("bed", animate=False)
    assert w._sleep_z.state == "sleep"
    w.jump()
    assert not w._sleep_z.particles.sleeping


def test_active_z_resizes_with_pet_and_reanchors_between_sleep_modes(env):
    w = env.win
    w.set_state("sleep", animate=False)
    z = w._sleep_z
    env.mono[0] += .9
    w.advance_to(env.mono[0])
    assert len(z.particles.born) == 2
    w.set_height(320)
    assert z.scale == 1.6 and len(z.particles.born) == 2
    w.set_state("bed", animate=False)
    assert z.state == "bed" and len(z.particles.born) == 1
    assert E.sleep_z_anchor(w, "bed").x() > w.x() + w.width() / 2


def test_native_z_input_styles(env):
    if QGuiApplication.platformName() != "windows":
        pytest.skip("需原生 Windows")
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    get_style = user32.GetWindowLongPtrW
    get_style.argtypes = [wintypes.HWND, ctypes.c_int]
    get_style.restype = ctypes.c_ssize_t
    env.win.show()
    env.win.set_state("sleep", animate=False)
    z = env.win._sleep_z
    for on in (False, True):
        env.ctl.set_always_on_top(on)
        style = get_style(int(z.winId()), -20)
        assert style & 0x20  # WS_EX_TRANSPARENT
        assert style & 0x08000000  # WS_EX_NOACTIVATE
        assert bool(style & 8) == on  # WS_EX_TOPMOST


@pytest.mark.parametrize("roll,double", [(0, True), (.1999, True), (.2, False), (.99, False)])
def test_desk_double_blink_probability_boundary_and_gap(monkeypatch, roll, double):
    p = B.PropPlayback(random.Random(1))
    p.reset(0)
    p.blink, p.sigh = 2.0, math.inf
    monkeypatch.setattr(p.rng, "random", lambda: roll)
    assert p.sprite("desk", 2) == "desk_2"
    assert p.sprite("desk", 2.15) == "desk_1"
    assert p.sprite("desk", 2.399) == "desk_1"
    assert p.sprite("desk", 2.4) == ("desk_2" if double else "desk_1")
    assert p.sprite("desk", 2.55) == "desk_1"


def test_desk_observed_frequency_and_sigh_cancels_second_blink():
    p = B.PropPlayback(random.Random(43))
    p.reset(0)
    p.sigh = math.inf
    double = 0
    for _ in range(1000):
        start = p.blink
        p.sprite("desk", start)
        assert 1.5 <= p.blink - start <= 3.5
        double += math.isfinite(p.second_blink)
    assert 150 < double < 250
    p.blink, p.sigh, p.second_blink = 20, 2.2, 2.4
    assert p.sprite("desk", 2.4) == "desk_3"
    assert math.isinf(p.second_blink)
    assert p.sprite("desk", 3.4) == "desk_1"


def working():
    a = Animator(random.Random(6))
    a.set_state("working", 0, immediate=True)
    a.calm = True  # 控制器工作状态默认 calm，也必须能点头。
    return a


def test_working_nod_timing_amplitude_and_return():
    a = working()
    for _ in range(20):
        at = a._next_nod
        a.frame(at)
        assert 3 <= a._next_nod - at <= 5
    at = a._next_nod
    for offset, pulse in [(0, 0), (.1, .5), (.2, 1), (.3, .5), (.4, 0)]:
        f = a.frame(at + offset)
        breath = 1 + A.WORKING_BREATH_AMP / 2 * (1 - math.cos(math.tau * (at + offset) / A.WORKING_BREATH_PERIOD))
        assert f.sy == pytest.approx(breath * (1 - .015 * pulse))
        assert f.angle == pytest.approx(pulse)


def test_nod_rng_is_independent_and_dropped_frames_do_not_replay():
    dense, sparse = working(), working()
    for t in np.arange(0, 100, .03):
        dense.frame(float(t))
    assert dense.frame(100) == sparse.frame(100)
    assert dense._nod_at == sparse._nod_at
    assert dense._rng.getstate() == sparse._rng.getstate()
    assert dense._next_nod == sparse._next_nod


@pytest.mark.parametrize("block", ["drag", "motion", "state"])
def test_working_nod_cancels_and_reschedules_when_blocked(block):
    a = working()
    at = a._next_nod
    assert a.frame(at + .2).angle == pytest.approx(1)
    if block == "drag":
        a.set_drag(True, at + .2)
    elif block == "motion":
        a.idle_enabled = False
    else:
        a.set_state("done", at + .2, immediate=True)
    a.frame(at + .21)
    assert math.isinf(a._next_nod)
    a.set_drag(False, 100)
    a.idle_enabled = True
    a.set_state("working", 100, immediate=True)
    a.frame(100)
    assert 103 <= a._next_nod <= 105


def test_neglect_sway_period_bounds_and_mutual_exclusion():
    a = Animator(random.Random(1))
    a.set_state("neglect2", 0, immediate=True)
    for t, expected in [(0, 0), (.875, 1.2), (1.75, 0), (2.625, -1.2), (3.5, 0)]:
        assert a.frame(t).angle == pytest.approx(expected, abs=1e-9)
        assert a.frame(t).sy == 1
    a.calm = True
    assert a.frame(.875).angle == 0
    a.calm = False
    a.activity_level = "quiet"
    assert a.frame(.875).angle == 0
    a.activity_level = "normal"
    a.idle_enabled = False
    assert a.frame(.875).angle == 0


@pytest.mark.parametrize("state", ["working", "neglect2"])
@pytest.mark.parametrize("height", [160, 200, 260, 320])
def test_new_poses_preserve_feet_and_mask_without_clipping(env, state, height):
    w = env.win
    w.set_height(height)
    w.set_state(state, animate=False)
    at = 100.875 if state == "neglect2" else w._animator._next_nod + .2
    feet = (w.x() + w.width() / 2, w.y() + w.height() - MARGIN_BOTTOM)
    w.advance_to(at)
    image = w.render_frame()
    ys, xs = np.where(alpha(image) > 0)
    assert len(xs) and xs.min() > 0 and ys.min() > 0
    assert xs.max() < image.width() - 1 and ys.max() < image.height() - 1
    assert all(w.mask().contains(QPoint(int(x), int(y))) for x, y in zip(xs, ys))
    assert (w.x() + w.width() / 2, w.y() + w.height() - MARGIN_BOTTOM) == feet


@pytest.mark.parametrize("args", [["--state", "sleep"], ["--state", "bed"],
    ["--state", "working", "--nod"], ["--state", "desk", "--desk-blink", "double"]])
def test_snapshot_supports_new_effects(qapp, tmp_path, args):
    from shion.__main__ import main
    out = tmp_path / "motion.png"
    assert main(["--snapshot", str(out), "--height", "320", "--at", ".2", *args]) == 0
    assert not QImage(str(out)).isNull()


@pytest.mark.skipif(QGuiApplication.platformName() == "offscreen", reason="需原生 Windows")
def test_native_z_window_does_not_activate(env):
    import ctypes
    if QGuiApplication.platformName() != "windows":
        pytest.skip("需原生 Windows")
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    foreground = user32.GetForegroundWindow()
    if not foreground:
        pytest.skip("当前没有有效前台窗口，不能证明焦点保持")
    env.win.show()
    env.win.set_state("sleep", animate=False)
    qapp = QGuiApplication.instance()
    qapp.processEvents()
    assert user32.GetForegroundWindow() == foreground
    assert env.win._sleep_z.isVisible() and not env.win._sleep_z.isActiveWindow()
