import random

import pytest

from shion.effects import LIFETIME, RISE, Particles, heart_path


def test_spawn_and_items_rise_and_fade():
    p = Particles(random.Random(1))
    p.spawn(10.0, 3)
    assert p.active
    first = p.items(10.0)
    mid = p.items(10.0 + LIFETIME / 2)
    assert len(first) == len(mid) == 1  # 请求多颗也只允许一颗
    for (x0, y0, s, a0), (x1, y1, _, a1) in zip(first, mid):
        assert y0 == 0 and y1 < y0  # 向上
        assert abs(y1) <= RISE
        assert a1 < a0  # 逐渐变淡
        assert 0.8 <= s <= 1.2


def test_expired_particles_are_removed():
    p = Particles(random.Random(1))
    p.spawn(0.0, 2)
    p.spawn(0.6, 1)
    p.update(LIFETIME + 0.01)
    assert len(p.items(LIFETIME + 0.01)) == 1  # 只剩后生成的
    p.update(0.6 + LIFETIME + 0.01)
    assert not p.active


def test_heart_path_has_area():
    assert heart_path(18).boundingRect().width() > 10


def test_particle_motion_eases_out_and_skips_expired_frames():
    p = Particles(random.Random(1))
    p.spawn(0, 1)
    y0 = p.items(0)[0][1]
    y1 = p.items(0.25)[0][1]
    y2 = p.items(0.5)[0][1]
    assert abs(y1 - y0) > abs(y2 - y1)  # 开始快，结尾慢
    direct = p.items(0.75)
    for i in range(45):
        p.update(i / 60)
    assert p.items(0.75) == direct
    p.update(2)
    assert not p.active


def test_particle_rate_limit_and_total_cap(monkeypatch):
    import shion.effects as e
    monkeypatch.setattr(e, "LIFETIME", 10)
    p = Particles()
    for t in (0, 0.1, 0.199999, 0.2, 0.4, 0.6, 0.8, 1.0, 1.2):
        p.spawn(t, 100)
    assert len(p.items(1.2)) == 6
    assert [x.born for x in p._ps] == [0, 0.2, 0.4, 0.6, 0.8, 1.0]
    p.spawn(20)
    assert len(p.items(20)) == 1


def test_new_pat_session_spawns_two_immediately_and_restarts_interval():
    p = Particles()
    p.spawn(100)
    p.spawn(100.1, start_session=True)  # 开始反馈不被旧的冒出间隔挡住
    assert [x.born for x in p._ps] == [100, 100.1, 100.1]
    p.spawn(100.299999)
    assert len(p.items(100.299999)) == 3
    p.spawn(100.3)
    assert len(p.items(100.3)) == 4  # 原生 perf_counter 数值下也接受恰好 0.2 秒


def test_initial_pair_and_regular_stream_can_reach_six_live_hearts():
    p = Particles()
    p.spawn(100, start_session=True)
    for t in (100.2, 100.4, 100.6, 100.8):
        p.spawn(t)
    assert len(p.items(100.8)) == 6
    p.spawn(100.9, start_session=True)
    assert len(p.items(100.9)) == 6  # 开始反馈也不能越过总数上限
    p.spawn(101)
    assert len(p.items(101)) == 5  # 最早两颗到期，正常只补一颗


def test_start_pair_respects_remaining_capacity_and_rejected_spawns_are_not_queued(monkeypatch):
    import shion.effects as e

    monkeypatch.setattr(e, "LIFETIME", 10)
    p = Particles()
    for t in (0, 0.2, 0.4, 0.6, 0.8):
        p.spawn(t)
    p.spawn(0.81, start_session=True)
    assert len(p.items(0.81)) == 6  # 只剩一个空位
    for i in range(20):
        p.spawn(0.82 + i / 100, start_session=True)
    p.update(20)
    assert not p.active
    p.spawn(20)
    assert len(p.items(20)) == 1  # 被丢弃的粒子不补播


def test_zero_requested_hearts_does_not_consume_the_start_feedback():
    p = Particles()
    p.spawn(100, 0, start_session=True)
    assert not p.active
    p.spawn(100, start_session=True)
    assert len(p.items(100)) == 2


def test_rise_uses_55_pixels_with_the_existing_ease_out():
    p = Particles()
    p.spawn(0)
    assert p.items(0.5)[0][1] == pytest.approx(-55 * 0.875)
