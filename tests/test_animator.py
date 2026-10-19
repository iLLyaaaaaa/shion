"""animator 纯逻辑测试：不依赖 Qt，时间全部手动给。"""
import random

import pytest

from shion import animator as A
from shion.animator import Animator, squash_scale


def make(state="idle", seed=1):
    a = Animator(random.Random(seed))
    a.set_state(state, 0.0)
    return a


def test_breath_bounds_and_period():
    a = make("idle")
    sys_ = [a.frame(t / 100).sy for t in range(0, 301)]
    assert min(sys_) == pytest.approx(1.0, abs=1e-6)
    assert max(sys_) == pytest.approx(1.012, abs=1e-4)
    # 周期 3 秒：t 和 t+3 相同
    assert a.frame(0.7).sy == pytest.approx(a.frame(3.7).sy, abs=1e-9)
    # 半周期最大
    assert a.frame(1.5).sy == pytest.approx(1.012, abs=1e-6)


def test_breath_also_in_neglect1_but_not_elsewhere():
    assert make("neglect1").frame(1.5).sy == pytest.approx(1.012, abs=1e-6)
    for st in ["happy", "dizzy", "working", "sleep", "neglect2", "drag", "stop"]:
        assert make(st).frame(1.5).sy == 1.0, st


def collect_blinks(a, duration, step=0.005):
    """返回每次眨眼的 (开始, 结束) 时间。"""
    spans, start, t = [], None, 0.0
    while t < duration:
        blinking = a.frame(t).sprite == "blink"
        if blinking and start is None:
            start = t
        if not blinking and start is not None:
            spans.append((start, t))
            start = None
        t += step
    return spans


def test_blink_only_in_idle():
    for st in ["happy", "dizzy", "working", "neglect1", "sleep"]:
        a = make(st)
        assert collect_blinks(a, 60) == [], st
    assert len(collect_blinks(make("idle"), 60)) > 5


def test_blink_interval_and_duration():
    a = make("idle", seed=7)
    spans = collect_blinks(a, 600)
    assert len(spans) > 50
    for s, e in spans:
        assert e - s == pytest.approx(A.BLINK_DURATION, abs=0.011)
    # 把连眨（间隔 ≈ 0.15s）合并后，簇与簇之间的间隔应在 3~6 秒
    gaps = []
    for (s1, e1), (s2, e2) in zip(spans, spans[1:]):
        gap = s2 - e1
        if gap > 1.0:
            gaps.append(gap)
    assert gaps
    assert min(gaps) >= 3.0 - 0.01
    assert max(gaps) <= 6.0 + 0.02 + A.DOUBLE_BLINK_GAP + A.BLINK_DURATION


def test_double_blink_ratio_near_15_percent():
    a = make("idle", seed=3)
    spans = collect_blinks(a, 4000)
    clusters, doubles = 0, 0
    i = 0
    while i < len(spans):
        clusters += 1
        if i + 1 < len(spans) and spans[i + 1][0] - spans[i][1] < 1.0:
            doubles += 1
            i += 2
        else:
            i += 1
    assert clusters > 600
    assert 0.10 < doubles / clusters < 0.20


def test_set_state_resets_blink_and_leaving_idle_stops_it():
    a = make("idle")
    a.set_state("happy", 1.0)
    assert a.frame(2.0).sprite == "happy"
    a.set_state("idle", 10.0)
    assert a.frame(10.0).sprite == "idle"  # 刚切回来不会立刻眨


@pytest.mark.parametrize("kind,low", [("click", 0.92), ("land", 0.88)])
def test_squash_curve(kind, low):
    dur = A.SQUASH[kind][0]
    a = make("idle")
    a.squash(100.0, kind)
    vals = [squash_scale(kind, dur * i / 200) for i in range(201)]
    assert min(vals) == pytest.approx(low, abs=1e-3)
    assert max(vals) > 1.0  # 后段有轻微反弹
    assert max(vals) < 1.0 + (1 - low)  # 反弹幅度小于压扁
    assert vals[0] == 1.0 and vals[-1] == 1.0
    # 结束之后精确回到 1（idle 的呼吸另算，用 happy 排除）
    h = make("happy")
    h.squash(0.0, kind)
    assert h.frame(dur + 0.001).sy == 1.0
    assert h.frame(dur + 0.001).sx == 1.0
    # 压扁时变宽
    mid = make("happy")
    mid.squash(0.0, kind)
    f = mid.frame(dur * 0.3)
    assert f.sy < 1.0 and f.sx > 1.0


def test_squash_unknown_kind_rejected():
    with pytest.raises(ValueError):
        make().squash(0.0, "boom")


def test_sway_limits():
    d = make("dizzy")
    angles = [d.frame(t / 100).angle for t in range(0, 300)]
    assert max(angles) == pytest.approx(5.0, abs=0.01)
    assert min(angles) == pytest.approx(-5.0, abs=0.01)
    h = make("happy")
    angles = [h.frame(t / 100).angle for t in range(0, 300)]
    assert max(angles) == pytest.approx(2.5, abs=0.01)
    assert make("idle").frame(0.5).angle == 0.0


def run_tilt(a, vx, seconds, t0=0.0, fps=60):
    t = t0
    for _ in range(int(seconds * fps)):
        t += 1 / fps
        a.feed_velocity(vx, t)
        f = a.frame(t)
    return f, t


def test_tilt_follows_velocity_with_clamp_and_sign():
    a = make("drag")
    a.set_drag(True)
    f, _ = run_tilt(a, 400, 1.0)  # 向右拖 → 目标 -6°
    assert f.angle == pytest.approx(-6.0, abs=0.1)
    a2 = make("drag")
    a2.set_drag(True)
    f, _ = run_tilt(a2, -400, 1.0)
    assert f.angle == pytest.approx(6.0, abs=0.1)
    a3 = make("drag")
    a3.set_drag(True)
    f, _ = run_tilt(a3, 100000, 1.0)  # 极快 → 限幅
    assert f.angle == pytest.approx(-A.TILT_MAX, abs=0.01)


def test_tilt_is_smooth_and_returns_to_zero_after_release():
    a = make("drag")
    a.set_drag(True)
    f, t = run_tilt(a, 800, 1 / 60)
    assert abs(f.angle) < A.TILT_MAX * 0.5  # 平滑：不会一帧到位
    f, t = run_tilt(a, 800, 1.0, t0=t)
    assert abs(f.angle) > 5
    a.set_drag(False)
    f = a.frame(t + 2.0)
    assert f.angle == 0.0


def test_velocity_ignored_when_not_dragging():
    a = make("idle")
    a.feed_velocity(1000, 0.1)
    assert a.frame(0.2).angle == 0.0


def test_effects_stack():
    a = make("dizzy")
    a.squash(0.0, "land")
    f = a.frame(0.075)
    assert f.angle > 2.0  # 晃动仍在
    assert f.sy < 1.0  # 压扁同时生效


def test_switch_fades_for_120ms_and_squashes_then_settles():
    a = make("working")
    a.set_state("done", 1.0)
    assert dict(a.frame(1.0).layers) == {"working": 1.0}
    mid = a.frame(1.06)
    weights = dict(mid.layers)
    assert 0 < weights["working"] < weights["done"] < 1
    assert sum(weights.values()) == pytest.approx(1)
    assert 0.96 < mid.sy < 1
    assert mid.sx > 1
    assert a.frame(1.12).layers == (("done", 1.0),)
    assert a.frame(1.19).sy > 1  # 轻微回弹
    assert a.frame(1.25).sy == 1


def test_interrupted_switch_keeps_current_blend_and_same_state_does_not_restart():
    a = make("working")
    a.set_state("done", 1)
    before = dict(a.frame(1.04).layers)
    a.set_state("happy", 1.04)
    assert dict(a.frame(1.04).layers) == pytest.approx(before)
    a.set_state("happy", 1.10)
    assert a.frame(1.17).layers == (("happy", 1.0),)


def test_switch_eases_from_current_angle_without_snapping():
    a = make("dizzy")
    before = a.frame(0.225)
    assert before.angle == pytest.approx(5)
    a.set_state("working", 0.225)
    assert a.frame(0.225).angle == before.angle
    assert 0 < a.frame(0.285).angle < before.angle
    assert a.frame(0.35).angle == 0


@pytest.mark.parametrize("name", ["happy", "dizzy", "working", "sleep", "idle"])
def test_calm_mode_keeps_breath_without_sway(name):
    a = make(name)
    a.calm = True
    assert a.frame(1.5).angle == 0
    assert a.frame(1.5).sy == pytest.approx(1.012)


def test_animation_result_does_not_depend_on_dropped_frames():
    dense, sparse = make(seed=88), make(seed=88)
    for i in range(1200):
        dense.frame(i / 60)
    f1, f2 = dense.frame(20.0), sparse.frame(20.0)
    assert f1 == f2
    for a in (dense, sparse):
        a.set_state("done", 20)
    for i in range(1, 8):
        dense.frame(20 + i / 60)
    assert dense.frame(20.5) == sparse.frame(20.5)


def test_tilt_ease_out_depends_on_elapsed_time_not_frame_count():
    dense, sparse = make("drag"), make("drag")
    for a in (dense, sparse):
        a.set_drag(True, 0)
        a.feed_velocity(400, 0)
    for i in range(1, 31):
        dense.frame(i / 60)
    assert dense.frame(0.5).angle == pytest.approx(sparse.frame(0.5).angle)
    for a in (dense, sparse):
        a.set_drag(False, 0.5)
    assert dense.frame(3).angle == sparse.frame(3).angle == 0
