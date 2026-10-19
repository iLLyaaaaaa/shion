import random

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
    for t in (0, 0.1, 0.59, 0.6, 1.2, 1.8, 2.4):
        p.spawn(t, 100)
    assert len(p.items(2.4)) == 3
    assert [x.born for x in p._ps] == [0, 0.6, 1.2]
    p.spawn(20)
    assert len(p.items(20)) == 1
