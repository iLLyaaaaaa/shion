import random

import pytest

from shion.behavior import (
    IDLE_INTERVALS, IDLE_TALK_COOLDOWN, SHAKE_DISTANCE, WALK_DURATION,
    WALK_HOP_HEIGHT, IdleBehavior, ShakeTracker, Walk,
)


def test_shake_requires_reversals_not_distance_or_jitter():
    s = ShakeTracker()
    s.reset(0)
    for i, x in enumerate((100, 200, 300, 299, 301, 298, 300)):
        assert not s.feed(x, i / 10)
    assert not s.marks
    assert not s.feed(s.extreme - SHAKE_DISTANCE, 1)
    assert len(s.marks) == 0
    s.feed(250, 1.1)
    assert len(s.marks) == 1


def test_shake_three_reversals_within_inclusive_window_latches():
    s = ShakeTracker()
    s.reset(0)
    for x, t in ((60, 0), (0, 0.5), (60, 1.5)):
        assert not s.feed(x, t)
    assert s.feed(0, 2.5)  # 三次反转跨度恰好 2s
    assert s.feed(0, 50)  # 达标后直到落地仍记得
    s.reset(0)
    assert not s.shaken and not s.marks


def test_slow_reversals_do_not_accumulate():
    s = ShakeTracker()
    for i, x in enumerate((60, 0, 60, 0, 60, 0)):
        assert not s.feed(x, i * 1.1)


@pytest.mark.parametrize("level", ["normal", "lively"])
def test_idle_intervals_and_pause_do_not_catch_up(level):
    b = IdleBehavior(random.Random(4))
    assert b.step(0, True, level) is None
    lo, hi = IDLE_INTERVALS[level]
    assert lo <= b.next_at <= hi
    due = b.next_at
    assert b.step(due - 0.001, True, level) is None
    assert b.step(due, True, level) in ("turn", "face", "jump", "expression", "talk")
    assert b.step(1000, False, level) is None
    assert b.next_at is None
    assert b.step(2000, True, level) is None
    assert 2000 + lo <= b.next_at <= 2000 + hi
    assert b.step(3000, True, "quiet") is None


def test_idle_talk_is_rare_and_respects_cooldown(monkeypatch):
    b = IdleBehavior(random.Random(4))
    monkeypatch.setattr(b.rng, "random", lambda: 0)
    b.step(0, True, "lively")
    first = b.next_at
    assert b.step(first, True, "lively") == "talk"
    assert b.step(b.next_at, True, "lively") != "talk"
    assert b.step(first + IDLE_TALK_COOLDOWN, True, "lively") == "talk"


@pytest.mark.parametrize("cross", [True, False])
def test_walk_bounds_direction_jumps_and_finishes(cross):
    walk = Walk(250, -100, 500, 10, cross=cross, rng=random.Random(3))
    prev_x = 250
    for i in range(1, int(walk.duration * 60)):
        x, jump, direction, done = walk.sample(10 + i / 60)
        assert -100 <= x <= 500
        assert 0 <= jump <= WALK_HOP_HEIGHT
        assert direction in (-1, 1)
        assert not done
        if abs(x - prev_x) > 0.1:
            # 转折刚好跨帧时，当前方向可以已更新；其余按速度方向。
            assert abs(x - prev_x) <= walk.speed / 60 + 0.001
        prev_x = x
    x, jump, _, done = walk.sample(10 + walk.duration)
    assert done and jump == 0
    if cross:
        assert x == -100
    else:
        assert walk.duration == WALK_DURATION
    assert walk.sample(10 + walk.duration + 10)[0] == x


def test_walk_sampling_is_independent_of_dropped_frames():
    dense = Walk(100, 0, 800, 0, rng=random.Random(3))
    sparse = Walk(100, 0, 800, 0, rng=random.Random(3))
    for i in range(599):
        dense.sample(i / 60)
    assert dense.sample(10) == sparse.sample(10)


@pytest.mark.parametrize("cross", [True, False])
def test_walk_handles_zero_width_screen(cross):
    w = Walk(50, 0, 0, 0, cross=cross)
    assert w.sample(20) == (0, 0, 1, True)
