"""S5：鼓脸颊随屏幕位置换边。离屏、假时钟；后台准备另一侧用真实线程，等它做完。

离屏屏幕可用区域 800×800：中线 x=400，死区 ±40（5% 宽度 = 40）。
"""
import time

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF

import shion.v3_window as vw
from shion.v3_display import SIDE_DEAD_MIN, desired_side
from tests.test_v3_display import make, qapp  # noqa: F401
from tests.test_v3_gestures import _clipped, gmove, grelease, press


# ---- 纯逻辑 ----
@pytest.mark.parametrize("x,current,want", [
    (700, "left", "left"), (700, "right", "left"),     # 右半边：鼓左脸颊（朝屏幕中间）
    (100, "left", "right"), (100, "right", "right"),   # 左半边：鼓右脸颊
    (439, "left", "left"), (439, "right", "right"),    # 死区内：保持
    (361, "right", "right"), (361, "left", "left"),
    (441, "right", "left"), (359, "left", "right"),    # 刚出死区
])
def test_desired_side_with_dead_zone(x, current, want):
    assert desired_side(x, 0, 800, current) == want


def test_dead_zone_is_5_percent_but_at_least_40px_and_respects_screen_origin():
    assert desired_side(1920 + 960 + 95, 1920, 1920, "right") == "right"   # 5% = 96
    assert desired_side(1920 + 960 + 97, 1920, 1920, "right") == "left"
    assert SIDE_DEAD_MIN == 40
    assert desired_side(300 + 41, 0, 600, "right") == "left"               # 5% = 30 < 40
    assert desired_side(300 + 39, 0, 600, "right") == "right"


# ---- 窗口 ----
def _window(qapp, x, height=200):  # noqa: F811
    w, t = make(qapp, height, 1.5)
    w.auto_side = True
    w.set_state("idle", animate=False)
    w.move(x - w.width() // 2, 200)
    w.show()
    t[0] += .1
    w.advance_to(t[0])
    return w, t


def _run(w, t, seconds, until=None, real_timeout=60.0):
    """假时钟推进 seconds；until 给了就推进到它为真（期间让后台线程有真实时间干活）。"""
    end = t[0] + seconds
    deadline = time.time() + real_timeout
    while t[0] < end or (until is not None and not until()):
        t[0] += w._timer.interval() / 1000
        w.advance_to(t[0])
        if until is not None and until():
            return True
        if t[0] >= end and until is None:
            return True
        if until is not None and t[0] >= end:
            time.sleep(.005)
        if time.time() > deadline:
            return False
    return True


def _find(w, kind):
    pts = [(x, y) for y in range(0, w.height(), 3) for x in range(0, w.width(), 3)
           if w._v3_hit(QPointF(x, y))[0] == kind]
    assert pts, kind
    cx, cy = np.mean(pts, axis=0)
    return QPoint(*min(pts, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2))


def test_startup_on_the_left_half_is_right_side_directly_without_a_transition(qapp):  # noqa: F811
    w, t = _window(qapp, 150)
    assert w.cheek_side == "right" and w._v3_rig.mirror_sum is not None
    assert w.v3_stats["side_switches"] == 0
    assert all(k[0] == "right" for k in w._v3_renderers)   # 启动用不到的左侧不留
    w.close()
    w2, t2 = _window(qapp, 650)
    assert w2.cheek_side == "left"
    w2.close()


def test_both_rigs_share_the_same_foot_and_visible_height():
    left, right = vw.shared_rig("left"), vw.load_rig("right")
    assert left.v3_foot == right.v3_foot
    assert left.v3_visible[1] == right.v3_visible[1] and left.v3_visible[3] == right.v3_visible[3]


def test_settling_on_the_other_half_switches_after_a_blink_with_a_pop(qapp):  # noqa: F811
    w, t = _window(qapp, 650)
    assert w.cheek_side == "left"
    geometry = (w.width(), w.height())
    w.move(150 - w.width() // 2, 200)
    _run(w, t, 0.3)
    assert w.cheek_side == "left" and w._v3_side_target is None       # 还没停稳 0.5 秒
    blink_seen = []

    def switched():
        if w._v3_side_blink is not None:
            blink_seen.append(w._v3_animator.time - w._v3_side_blink)
        return w.cheek_side == "right"

    assert _run(w, t, 0.4, until=switched)
    assert w.v3_stats["side_switches"] == 1
    assert blink_seen                                              # 先眨眼……
    assert vw.SIDE_SWAP_AT <= w.v3_side_log[-1]["blink_elapsed"] < 0.1   # ……在闭眼最深附近换（0.06 秒）
    assert w._v3_animator.delta[0] < 0                             # 新侧鼓脸颊“啵”：先外拉
    assert w._v3_animator.reaction.active is False                 # 不触发捏脸反应脸
    assert (w.width(), w.height()) == geometry                     # 窗口几何不变
    assert w.v3_side_log[-1]["from"] == "left" and w.v3_side_log[-1]["to"] == "right"
    _run(w, t, 2.0)
    assert not np.any(w._v3_animator.delta)                         # 弹回去了
    assert _clipped(w) == 0
    w.close()


def test_no_switch_while_pressed_and_switch_after_release(qapp):  # noqa: F811
    w, t = _window(qapp, 650)
    w.move(150 - w.width() // 2, 200)
    body = _find(w, "body")
    press(w, body)
    _run(w, t, 3.0)
    assert w.cheek_side == "left" and w._v3_side_target is None
    g0 = w.mapToGlobal(body)
    grelease(w, g0, 0, 0)
    assert _run(w, t, 0.4, until=lambda: w.cheek_side == "right")
    w.close()


def test_inside_the_dead_zone_nothing_is_prepared(qapp):  # noqa: F811
    w, t = _window(qapp, 650)
    w.move(380 - w.width() // 2, 200)
    _run(w, t, 3.0)
    assert w.cheek_side == "left" and w._v3_side_target is None and w._v3_side_job is None
    w.close()


def test_moving_back_before_the_switch_cancels_the_preparation(qapp):  # noqa: F811
    w, t = _window(qapp, 650)
    w.move(150 - w.width() // 2, 200)
    _run(w, t, 0.6)
    assert w._v3_side_target == "right"
    w.move(650 - w.width() // 2, 200)
    _run(w, t, 1.0)
    assert w._v3_side_target is None and w.cheek_side == "left"
    assert w.v3_stats["side_switches"] == 0
    w.close()


def test_old_side_is_released_after_5_minutes_idle(qapp):  # noqa: F811
    w, t = _window(qapp, 650)
    w.move(150 - w.width() // 2, 200)
    assert _run(w, t, 0.4, until=lambda: w.cheek_side == "right")
    assert any(k[0] == "left" for k in w._v3_renderers)
    _run(w, t, 200)
    assert any(k[0] == "left" for k in w._v3_renderers)            # 不到 5 分钟还在
    _run(w, t, 110)
    assert not any(k[0] == "left" for k in w._v3_renderers) and "left" not in vw._RIGS
    w.close()
    vw.shared_rig("left")


def test_right_side_pinch_pulls_outward_and_lift_moves_the_window(qapp):  # noqa: F811
    w, t = _window(qapp, 150, height=260)
    assert w.cheek_side == "right"
    _run(w, t, 1.0)
    cheek = _find(w, "cheek")
    neck_x = w._v3_rig.pivots["neck"][0]
    assert w._v3_hit(QPointF(cheek))[2][0] > neck_x                  # 命中在右脸颊
    spy = []
    w.gesture.connect(spy.append)
    g0 = w.mapToGlobal(cheek)
    press(w, cheek)
    gmove(w, g0, 20, 0)
    gmove(w, g0, 50, 0)                                               # 往外（屏幕右边）拉
    _run(w, t, .05)
    assert w._v3_animator.delta[0] < -10                              # 左侧语义：外拉为负
    assert spy.count("cheek_pull") == 1
    grelease(w, g0, 50, 0)
    _run(w, t, 1.5)
    origin = w.pos()
    g1 = w.mapToGlobal(cheek)
    press(w, cheek)
    gmove(w, g1, 0, -40)
    assert w.lifting and w.pos().y() == origin.y() - 40
    t[0] += 1
    w.advance_to(t[0])
    grelease(w, g1, 0, -40)
    w.close()


def test_switch_frame_does_not_compose_on_the_main_thread(qapp):  # noqa: F811
    w, t = _window(qapp, 650, height=260)
    w.move(150 - w.width() // 2, 200)
    costs = []

    def step():
        before = w.cheek_side
        t0 = time.perf_counter()
        w.advance_to(t[0])
        if w.cheek_side != before:
            costs.append((time.perf_counter() - t0) * 1000)
        return bool(costs)

    deadline = time.time() + 60
    while not costs and time.time() < deadline:
        t[0] += w._timer.interval() / 1000
        step()
        time.sleep(.003)
    assert costs, "never switched"
    print("switch frame ms", costs)
    assert costs[0] < 40, costs
    w.close()


def test_auto_side_is_on_by_default_and_env_turns_it_off(qapp, monkeypatch):  # noqa: F811
    from shion.v3_window import AUTO_SIDE_ENV, V3PetWindow
    monkeypatch.delenv(AUTO_SIDE_ENV, raising=False)
    t = [100.0]
    w = V3PetWindow(height=200, clock=lambda: t[0], autostart=False, debug=False, pixel_ratio=1.0)
    assert w.auto_side is True
    w.close()
    monkeypatch.setenv(AUTO_SIDE_ENV, "0")
    w2 = V3PetWindow(height=200, clock=lambda: t[0], autostart=False, debug=False, pixel_ratio=1.0)
    assert w2.auto_side is False
    w2.move(150 - w2.width() // 2, 200)
    w2.show()
    for _ in range(100):
        t[0] += .05
        w2.advance_to(t[0])
    assert w2.cheek_side == "left" and w2._v3_side_target is None    # 关掉后左半边也保持左鼓
    w2.close()


# ---- R1：启动按存档位置选侧、丢弃一侧后补一次 GC ----
from concurrent.futures import Future  # noqa: E402
import types  # noqa: E402
import weakref  # noqa: E402

from PySide6.QtCore import Qt  # noqa: E402

from shion.v3_display import startup_side  # noqa: E402

SCREEN = [(0, 0, 800, 800)]


def test_startup_side_from_the_saved_position():
    assert startup_side(None, None, 200, SCREEN) is None                 # 没有存档位置：默认右下角
    assert startup_side(True, None, 200, SCREEN) is None                 # bool 不是位置
    assert startup_side(50, None, 200, SCREEN) == "right"                # 窗口中心在左半
    assert startup_side(600, 300, 200, SCREEN) == "left"
    assert startup_side(270, None, 200, SCREEN) == "left"                # 中线死区内保持默认（左鼓）
    assert startup_side(5000, 300, 200, SCREEN) is None                  # 那块屏被拔了
    two = [(0, 0, 800, 800), (800, 0, 800, 800)]
    assert startup_side(850, 300, 200, two) == "right"                   # 第二块屏的左半
    assert startup_side(1400, 300, 200, two) == "left"


@pytest.mark.parametrize("height", [160, 200, 260, 320])
def test_the_window_width_estimate_matches_the_real_window(qapp, height):  # noqa: F811
    from shion.v3_display import WINDOW_MARGIN_X, WINDOW_WIDTH_RATIO
    w, _ = make(qapp, height, 1.5)
    assert abs(w.width() - (round(WINDOW_WIDTH_RATIO * height) + 2 * WINDOW_MARGIN_X)) <= 6
    w.close()


def _hinted(qapp_, monkeypatch, hint, x):
    """按提示直接构造（不经 make）；rig 缓存换成空的，记录实际加载过哪些侧。"""
    loaded = []
    real = vw.load_rig
    monkeypatch.setattr(vw, "_RIGS", {})
    monkeypatch.setattr(vw, "load_rig", lambda side: (loaded.append(side), real(side))[1])
    t = [100.0]
    w = vw.V3PetWindow(height=200, clock=lambda: t[0], autostart=False, debug=False,
                       pixel_ratio=1.5, initial_side=hint)
    w.setAttribute(Qt.WA_DontShowOnScreen)
    w.set_state("idle", animate=False)
    w.move(x - w.width() // 2, 200)
    w.show()
    t[0] += .1
    w.advance_to(t[0])
    return w, t, loaded


def test_a_right_hint_on_the_left_half_loads_only_the_right_side(qapp, monkeypatch):  # noqa: F811
    w, t, loaded = _hinted(qapp, monkeypatch, "right", 150)
    assert loaded == ["right"] and w.cheek_side == "right"
    assert w._v3_gc_wait is None and list(vw._RIGS) == ["right"]       # 没有丢弃过任何一侧
    w.close()


def test_a_wrong_hint_is_corrected_on_first_show(qapp, monkeypatch):  # noqa: F811
    w, t, loaded = _hinted(qapp, monkeypatch, "left", 150)
    assert loaded == ["left", "right"] and w.cheek_side == "right"
    assert list(vw._RIGS) == ["right"]                                  # 左侧丢了
    assert w._v3_gc_wait is None and w.v3_stats["gc_ms"] > 0.0          # 随后那一帧就补了一次 GC（任务已结束、没在互动）
    w.close()


def test_no_hint_means_left_and_auto_side_off_ignores_the_hint(qapp, monkeypatch):  # noqa: F811
    w, t, loaded = _hinted(qapp, monkeypatch, None, 650)
    assert loaded == ["left"] and w.cheek_side == "left"
    w.close()
    monkeypatch.setenv(vw.AUTO_SIDE_ENV, "0")
    w, t, loaded = _hinted(qapp, monkeypatch, "right", 150)
    assert loaded == ["left"] and w.cheek_side == "left"
    w.close()


def test_prewarmer_close_returns_only_tasks_that_are_running(qapp):  # noqa: F811
    w, t = _window(qapp, 650)
    pre = w._v3_prewarmer
    queued, running, done = Future(), Future(), Future()
    running.set_running_or_notify_cancel()
    done.set_result(1)
    pre.pending = {("a",): queued, ("b",): running, ("c",): done}
    assert pre.close() == [running] and queued.cancelled() and pre.pending == {}
    w.close()


def test_gc_runs_once_after_a_drop_when_tasks_are_done_and_idle(qapp, monkeypatch):  # noqa: F811
    w, t = _window(qapp, 650)
    calls = []
    monkeypatch.setattr(vw, "gc", types.SimpleNamespace(collect=lambda *a: calls.append(1) or 0))
    running = Future()
    running.set_running_or_notify_cancel()
    w._v3_gc_wait = [running]
    w._v3_side_step(t[0])
    assert not calls                                   # 后台任务还在跑
    running.set_result(None)
    monkeypatch.setattr(w, "_v3_busy", lambda: True)
    w._v3_side_step(t[0])
    assert not calls                                   # 在互动，等停手
    monkeypatch.setattr(w, "_v3_busy", lambda: False)
    w._v3_side_step(t[0])
    assert calls == [1] and w._v3_gc_wait is None and w.v3_stats["gc_ms"] >= 0.0
    w._v3_side_step(t[0])
    assert calls == [1]                                # 只做一次
    w.close()


def test_the_released_side_is_really_freed_and_gc_ran_once(qapp, monkeypatch):  # noqa: F811
    w, t = _window(qapp, 650)
    w.move(150 - w.width() // 2, 200)
    assert _run(w, t, 0.4, until=lambda: w.cheek_side == "right")
    left = next(r for k, r in w._v3_renderers.items() if k[0] == "left")
    rig_ref, renderer_ref = weakref.ref(left.rig), weakref.ref(left)
    del left
    calls = []
    real_gc = vw.gc
    monkeypatch.setattr(vw, "gc", types.SimpleNamespace(
        collect=lambda *a: (calls.append(1), real_gc.collect())[1]))
    _run(w, t, 310)
    assert not any(k[0] == "left" for k in w._v3_renderers) and "left" not in vw._RIGS
    assert calls == [1] and w._v3_gc_wait is None
    assert rig_ref() is None and renderer_ref() is None
    w.close()
    vw.shared_rig("left")


def test_closing_the_window_cancels_the_side_preparation(qapp):  # noqa: F811
    w, t = _window(qapp, 650)
    w.move(150 - w.width() // 2, 200)
    _run(w, t, 0.6)
    assert w._v3_side_target == "right"
    w.close()
    assert w._v3_side_target is None and w._v3_side_job is None
