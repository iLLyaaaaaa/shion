"""S7 审查修复：大 dt、右键不打断手势、帧缓存淘汰后重新预热、仿射 QImage 缓存上限、
后台预热线程关闭、主线程不等后台锁。"""
import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest

from shion.v3_prewarm import BLINK_LEVELS, FRAME_LIMIT, Prewarmer, _BackgroundExecutor
from tests.test_v3_display import SyncExecutor, make, qapp, run_for  # noqa: F401
from tests.test_v3_gestures import _lift_start, _step, find, gmove, grelease, press, release, window


# ---- 1. 大 dt ----
def test_a_long_gap_advances_the_animation_by_at_most_max_dt(qapp):  # noqa: F811
    from shion.v3_window import MAX_DT
    w, t, _ = window(qapp, 200)
    run_for(w, t, .5)
    before = w._v3_animator.time
    t[0] += 600.0                      # 隐藏 10 分钟 / 睡眠恢复
    start = time.perf_counter()
    w.advance_to(t[0])
    assert time.perf_counter() - start < 0.2
    assert w._v3_animator.time - before <= MAX_DT + 1e-6
    w.close()


# ---- 5. 右键不打断左键手势 ----
def _right(w, kind, pos):
    etype = QEvent.MouseButtonPress if kind == "press" else QEvent.MouseButtonRelease
    buttons = Qt.LeftButton | Qt.RightButton if kind == "press" else Qt.LeftButton
    event = QMouseEvent(etype, QPointF(pos), QPointF(w.mapToGlobal(pos)), Qt.RightButton,
                        buttons, Qt.NoModifier)
    (w.mousePressEvent if kind == "press" else w.mouseReleaseEvent)(event)


def test_right_click_during_a_lift_does_not_leave_the_lift_stuck(qapp):  # noqa: F811
    w, t, spy, g0 = _lift_start(qapp)
    gmove(w, g0, 0, -20)
    assert w.lifting
    local = w.mapFromGlobal(g0)
    _right(w, "press", local)
    _right(w, "release", local)
    assert w.lifting and w._v3_gesture is not None   # 右键没把手势清掉
    t[0] += 1.0
    w.advance_to(t[0])
    grelease(w, g0, 0, -20)
    assert not w.lifting and spy.finished == [1]
    assert w._v3_animator.lift.released_at is not None
    assert w._v3_gesture is None
    w.close()


def test_right_click_during_a_pinch_keeps_the_pinch(qapp):  # noqa: F811
    w, t, spy = window(qapp, 320)
    start = find(w, "cheek")
    press(w, start)
    QTest.mouseMove(w, start - type(start)(30, 0))
    _step(w, t)
    _right(w, "press", start)
    _right(w, "release", start)
    assert w._v3_gesture == "cheek"
    release(w, start - type(start)(30, 0))
    assert w._v3_gesture is None and "cheek_release" in spy.gesture
    w.close()


# ---- 2. 帧缓存淘汰后重新预热；当前表情不被挤掉 ----
def _fake_prewarmer(expression="neutral"):
    frames = {}
    from collections import OrderedDict
    frames = OrderedDict()
    surface = SimpleNamespace(frames=frames, cheek=SimpleNamespace(config=None), _v3_cheek_done=set(),
                              _compose_image=lambda *a, **k: None,
                              reaction_face=SimpleNamespace(patch=lambda *a, **k: None, cache={}))
    surface.cheek.prepare = lambda *a, **k: None
    from dataclasses import dataclass

    @dataclass
    class S:
        expression: str = "neutral"
    executor = SyncExecutor()
    p = Prewarmer(SimpleNamespace(head_surface=surface), S(expression), executor=executor)
    p._build = lambda settings, level: ("frame", settings.expression, level)
    return p, frames, executor


def test_evicted_frames_are_prewarmed_again_and_the_current_expression_is_kept():
    p, frames, executor = _fake_prewarmer("neutral")
    p.request("neutral")
    p.request_blinks("neutral")
    p.collect()
    assert all(("neutral", level) in frames for level in BLINK_LEVELS)
    # 其它表情把缓存塞满：先淘汰别的表情，当前表情一张不少
    for i in range(FRAME_LIMIT):
        p.request(f"other{i}")
        p.collect()
    assert len(frames) == FRAME_LIMIT
    assert all(("neutral", level) in frames for level in BLINK_LEVELS)
    assert ("other0", 1.0) not in frames
    # 切回被挤掉的表情：后台重新请求，不靠主线程现算
    p.settings.expression = "other0"
    calls = executor.calls
    p.request("other0")
    p.request_blinks("other0")
    assert executor.calls == calls + len(BLINK_LEVELS)
    p.collect()
    assert ("other0", 1.0) in frames and ("other0", BLINK_LEVELS[0]) in frames


class CatchingExecutor(SyncExecutor):
    def submit(self, fn, *args):
        from concurrent.futures import Future
        self.calls += 1
        f = Future()
        try:
            f.set_result(fn(*args))
        except Exception as e:  # noqa: BLE001
            f.set_exception(e)
        return f


def test_failed_prewarm_is_not_retried_every_frame():
    p, frames, _ = _fake_prewarmer()
    executor = p.executor = CatchingExecutor()

    def boom(settings, level):
        raise RuntimeError("x")
    p._build = boom
    p.request("neutral")
    p.collect()
    calls = executor.calls
    for _ in range(5):
        p.request("neutral")
        p.collect()
    assert executor.calls == calls and ("neutral", 1.0) not in frames


# ---- 3. 仿射路径 QImage 缓存上限 ----
def test_affine_qimage_cache_stays_small_through_a_blink(qapp):  # noqa: F811
    from shion.v3_layers import QFRAME_LIMIT
    w, t, _ = window(qapp, 200)
    surface = w._v3_renderer.head_surface
    for expression in ("neutral", "happy", "smug"):
        w._v3_prewarmer.request_blinks(expression)
    run_for(w, t, 6.0)
    assert len(surface.__dict__.get("_v3_qframes", {})) <= QFRAME_LIMIT
    w.close()


# ---- 4. 后台线程关闭 ----
def test_shutdown_cancels_queued_work_and_joins_the_thread():
    ex = _BackgroundExecutor()
    gate = threading.Event()
    first = ex.submit(gate.wait, 5)
    queued = [ex.submit(lambda: 1) for _ in range(3)]
    time.sleep(0.05)
    gate.set()
    assert ex.shutdown(timeout=2.0)
    assert first.done() and all(f.cancelled() for f in queued)
    late = ex.submit(lambda: 1)
    assert late.cancelled()


def test_shared_pool_is_rebuilt_after_shutdown():
    pool = Prewarmer._shared_pool()
    assert Prewarmer.shutdown_pool()
    again = Prewarmer._shared_pool()
    assert again is not pool and again.submit(lambda: 7).result(timeout=2) == 7


# ---- 6. 主线程不等后台锁 ----
def _hold_lock(lock, ready, release):
    with lock:
        ready.set()
        release.wait(5)


class IdleExecutor:
    """收下任务但永远不跑：主线程只能自己合成（模拟后台还没轮到）。"""

    def submit(self, fn, *args):
        from concurrent.futures import Future
        return Future()


def test_a_frame_that_needs_the_busy_lock_is_deferred_not_waited_for(qapp, monkeypatch):  # noqa: F811
    import shion.v3_window as vw
    monkeypatch.setattr(vw, "PREWARM_EXECUTOR", IdleExecutor())
    w, t = make(qapp, 200, 1.0)
    w.set_state("stop", animate=False)       # stop → angry，主线程自己合成
    run_for(w, t, .3)
    surface = w._v3_renderer.head_surface
    assert w._v3_settings.expression == "angry"
    for key in [k for k in surface.frames if k[0] == "angry"]:
        del surface.frames[key]               # 生气脸的帧被淘汰了，要现算
    w._v3_key = None                          # 强制这一帧重画
    old_image = w._v3_image
    ready, release_lock = threading.Event(), threading.Event()
    holder = threading.Thread(target=_hold_lock, args=(surface._v3_lock, ready, release_lock))
    holder.start()
    ready.wait(2)
    try:
        t[0] += .05
        start = time.perf_counter()
        w.advance_to(t[0])
        assert time.perf_counter() - start < 0.03
        assert w._v3_image is old_image and w.v3_stats["deferred"] >= 1
    finally:
        release_lock.set()
        holder.join(2)
    t[0] += .05
    w.advance_to(t[0])
    assert w._v3_image is not old_image and ("angry", 1.0) in surface.frames
    w.close()


def test_cached_reaction_patch_does_not_take_the_lock(qapp):  # noqa: F811
    w, t, _ = window(qapp, 200)
    surface = w._v3_renderer.head_surface
    patch = surface.reaction_face.patch
    patch("dizzy")                       # 确保已缓存
    ready, release_lock = threading.Event(), threading.Event()
    holder = threading.Thread(target=_hold_lock, args=(surface._v3_lock, ready, release_lock))
    holder.start()
    ready.wait(2)
    try:
        start = time.perf_counter()
        patch("dizzy")
        assert time.perf_counter() - start < 0.01
    finally:
        release_lock.set()
        holder.join(2)
    w.close()
