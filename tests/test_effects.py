import random

from shion.effects import LIFETIME, RISE, Particles, heart_path


def test_spawn_and_items_rise_and_fade():
    p = Particles(random.Random(1))
    p.spawn(10.0, 3)
    assert p.active
    first = p.items(10.0)
    mid = p.items(10.0 + LIFETIME / 2)
    assert len(first) == len(mid) == 3
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
