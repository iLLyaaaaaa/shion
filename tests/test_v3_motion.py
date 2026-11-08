"""Numerical contracts, independent of Qt and art assets."""
import random

import numpy as np
import pytest

from v3proto.animation import Animator, Settings, SWAY_PARTS
from v3proto.motion import (Spring, bend_inverse, blink_scale, blink_schedule, breathing,
                            limit_vector, pinch_inverse, pivot_matrix, release_step,
                            spring_step, transform_point, translation)


def test_spring_converges_and_crosses_rest():
    s = Spring(120, 0)
    positions = []
    for _ in range(360):
        s = spring_step(s, 1 / 120)
        positions.append(s.position)
    assert min(positions) < -20
    assert abs(s.position) < 1e-4 and abs(s.velocity) < 1e-3


@pytest.mark.parametrize("dt", [1 / 240, 1 / 60, 0.2])
def test_spring_time_step_independence(dt):
    s = Spring(4, -2)
    count = round(1 / dt)
    for _ in range(count):
        s = spring_step(s, 1 / count, target=2)
    expected = spring_step(Spring(4, -2), 1, target=2)
    assert s.position == pytest.approx(expected.position, abs=1e-12)
    assert s.velocity == pytest.approx(expected.velocity, abs=1e-12)


def test_blink_timing_and_random_intervals():
    assert blink_scale(-0.01) == blink_scale(0) == blink_scale(0.15) == 1
    assert blink_scale(0.06) == pytest.approx(0.1)
    assert blink_scale(0.03) == pytest.approx(0.55)
    assert blink_scale(0.105) == pytest.approx(0.55)
    assert blink_scale(0.06, 0) == 1
    schedule = blink_schedule(random.Random(7), 3600)
    assert schedule == blink_schedule(random.Random(7), 3600)
    gaps = np.diff(schedule)
    doubles = np.isclose(gaps, 0.24)
    assert doubles.any() and 0.05 < doubles.mean() < 0.25
    assert ((gaps[~doubles] >= 3) & (gaps[~doubles] <= 6)).all()


def test_pivot_parent_and_inverse():
    pivot = (20, 30)
    m = translation(4, -5) @ pivot_matrix(pivot, 90, sy=1.012)
    assert transform_point(m, pivot) == pytest.approx([24, 25])
    assert transform_point(pivot_matrix((0, 0), 90), (10, 0)) == pytest.approx([0, 10])
    point = [33, 44]
    assert transform_point(np.linalg.inv(m), transform_point(m, point)) == pytest.approx(point)


def test_breath_limits_and_period():
    samples = np.array([breathing(t) for t in np.linspace(0, 3.5, 1001)])
    assert samples[:, 0].min() == pytest.approx(1)
    assert samples[:, 0].max() == pytest.approx(1.012)
    assert 1 < np.ptp(samples[:, 1]) * 0.4 < 2
    assert breathing(0.4) == pytest.approx(breathing(3.9))


def test_bend_has_fixed_root_and_no_row_jumps():
    y = np.linspace(10, 310, 1000)
    x = np.full_like(y, 50)
    sx, sy = bend_inverse(x, y, (50, 10), 300, 3)
    assert sx[0] == 50 and np.array_equal(sy, y)
    assert sx[-1] < sx[0]
    assert abs(np.diff(sx)).max() < 0.04


def test_fringe_root_stays_attached_while_lower_fringe_rotates():
    from v3proto.motion import rooted_rotation_inverse
    x=np.array([0.,20.,50.]);y=np.array([90.,100.,80.])
    sx,sy=rooted_rotation_inverse(x,y,(25,100),3,[(0,100),(50,100)])
    assert np.array_equal(sx,x) and np.array_equal(sy,y)
    x=np.array([20.,30.]);y=np.array([300.,300.])
    sx,sy=rooted_rotation_inverse(x,y,(25,100),3,[(0,100),(50,100)])
    expected=[transform_point(pivot_matrix((25,100),-3),p) for p in zip(x,y)]
    assert np.column_stack([sx,sy])==pytest.approx(np.asarray(expected))


@pytest.mark.parametrize("maximum,radius", [(20, 160), (120, 110), (200, 60)])
def test_pinch_limit_inverse_anchor_and_no_folds(maximum, radius):
    d = limit_vector((999, 999), maximum)
    assert np.linalg.norm(d) == pytest.approx(maximum)
    center = np.array([0., 0.])
    px, py = pinch_inverse(np.array([d[0]]), np.array([d[1]]), center, d, radius, maximum)
    assert px[0] == pytest.approx(0, abs=1e-5) and py[0] == pytest.approx(0, abs=1e-5)
    y, x = np.mgrid[-400:401:4, -400:401:4].astype(np.float32)
    sx, sy = pinch_inverse(x, y, center, (maximum, 0), radius, maximum)
    assert (np.diff(sx, axis=1) > 0).all()
    assert np.isfinite(sx).all() and np.isfinite(sy).all()
    z = pinch_inverse(x, y, center, (0, 0), radius, maximum)
    assert np.array_equal(z[0], x) and np.array_equal(z[1], y)


def test_pinch_release_overshoots_but_stays_bounded():
    p, v = np.array([200., 0.]), np.zeros(2)
    xs = []
    for _ in range(400):
        p, v = release_step(p, v, 1 / 120, 200)
        assert np.linalg.norm(p) <= 200 + 1e-9
        xs.append(p[0])
    assert min(xs) < -50
    assert np.array_equal(p, [0, 0])


def test_pinch_attachment_rows_stay_fixed_at_extreme_pull():
    x = np.array([400., 550., 700.], dtype=np.float32)
    for yy in (350., 668.):
        y = np.full_like(x, yy)
        sx, sy = pinch_inverse(x, y, (650, 580), (150, 132), 160, 200, (350, 668))
        assert np.array_equal(sx, x) and np.array_equal(sy, y)


def test_switches_clear_pending_motion_and_face_switch_opens_eyes():
    settings = Settings()
    a = Animator(settings)
    a.advance(a.blink_start + 0.06)
    assert a.pose.eye_scale < 0.11
    settings.expression = "happy"
    assert a.advance(0).eye_scale == 1
    a.press((500, 530))
    a.drag((-999, 530))
    assert np.linalg.norm(a.delta) == pytest.approx(120)
    a.impulse()
    a.advance(0.1)
    settings.breath = settings.blink = settings.sway = settings.pinch = False
    assert a.advance(0).is_rest
    assert not a.dragging


def test_seeded_motion_is_repeatable_and_impulse_is_bounded():
    a, b = Animator(Settings(), 10), Animator(Settings(), 10)
    for _ in range(120):
        assert a.advance(1 / 60) == b.advance(1 / 60)
    a.impulse(100)
    for _ in range(120):
        p = a.advance(1 / 60)
        assert all(abs(p.angles[n]) <= (8 if n=='ahoge' else 2) for n in SWAY_PARTS)


def test_breath_neck_follows_torso_without_sliding():
    for t in np.linspace(0,3.5,300):
        scale,head=breathing(t)
        neck=(664-1063.4)*(scale-1)
        assert abs(head-neck)<.09
    for t in (0,3.5*.42,3.5):
        before=breathing(t-1e-4)[1]
        after=breathing(t+1e-4)[1]
        assert abs(after-before)<.001
