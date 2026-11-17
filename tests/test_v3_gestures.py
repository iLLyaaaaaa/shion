"""S3：V3 窗口的捏脸 / 敲头 / 摸头 / 挠痒手势，以及与台词、好感的衔接。

离屏、假时钟、真实 Qt 鼠标事件；不依赖真人鼠标。
"""
import json
import math
import time
from dataclasses import replace

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest

from shion.lines import LINES_DIR
from tests.test_controller import env  # noqa: F401  (fixture)
from tests.test_v3_display import make, qapp, run_for  # noqa: F401  (fixtures/helpers)

_POINTS: dict = {}


def find(w, kind):
    """窗口里 V3 命中为 kind 的点里，最靠近这些点重心的那个（缓存）。"""
    key = (w.height(), w._v3_dpr, kind)
    if key not in _POINTS:
        pts = []
        for y in range(0, w.height(), 3):
            for x in range(0, w.width(), 3):
                if w._v3_hit(QPointF(x, y))[0] == kind:
                    pts.append((x, y))
        assert pts, kind
        cx, cy = np.mean(pts, axis=0)
        _POINTS[key] = QPoint(*min(pts, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2))
    return _POINTS[key]


class Spy:
    def __init__(self, w):
        self.gesture, self.patted, self.clicked, self.knocked, self.drags = [], [], [], [], []
        self.ignored, self.finished = [], []
        w.gesture.connect(self.gesture.append)
        w.patted.connect(lambda: self.patted.append(1))
        w.clicked.connect(lambda: self.clicked.append(1))
        w.knocked.connect(self.knocked.append)
        w.drag_started.connect(lambda: self.drags.append(1))
        w.drag_ignored.connect(lambda: self.ignored.append(1))
        w.drag_finished.connect(lambda: self.finished.append(1))


def window(qapp, height=320):  # noqa: F811
    w, t = make(qapp, height, 1.5)
    w.set_state("idle", animate=False)
    t[0] += .5
    w.advance_to(t[0])
    return w, t, Spy(w)


def press(w, pos):
    QTest.mousePress(w, Qt.LeftButton, Qt.NoModifier, pos)


def move(w, pos):
    QTest.mouseMove(w, pos)


def release(w, pos):
    QTest.mouseRelease(w, Qt.LeftButton, Qt.NoModifier, pos)


def gmove(w, g0, dx, dy):
    """鼠标移到“按下点 + (dx, dy)”的全局坐标（窗口被拖动后本地坐标会变，所以用全局）。"""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent
    g = QPoint(g0.x() + dx, g0.y() + dy)
    w.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, QPointF(w.mapFromGlobal(g)), QPointF(g),
                                 Qt.NoButton, Qt.LeftButton, Qt.NoModifier))


def grelease(w, g0, dx, dy):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent
    g = QPoint(g0.x() + dx, g0.y() + dy)
    w.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, QPointF(w.mapFromGlobal(g)), QPointF(g),
                                    Qt.LeftButton, Qt.NoButton, Qt.NoModifier))


def click(w, pos):
    press(w, pos)
    release(w, pos)


def assert_clean(w):
    assert not w.is_pressed and not w._pat_mode
    assert w._v3_gesture is None


# ---- 命中映射 ----
def test_widget_to_rig_round_trip_including_squash_tilt_and_jump(qapp):
    w, t, _ = window(qapp, 200)
    rig = w._v3_rig
    s, gap = w._v3_scale, w._height * 8 / 512
    foot_x, foot_y = rig.v3_foot
    base = w._frame
    for frame, jump in ((base, 0.0),
                        (replace(base, sx=1.08, sy=.9, angle=2.5), 0.0),
                        (replace(base, sx=.95, sy=1.04, angle=-3.0), 12.0)):
        w._frame, w._jump_offset = frame, jump
        transform = w._v3_transform(frame)
        for rig_point in ((543.0, 300.0), (400.0, 700.0), (600.0, 900.0)):
            image = QPointF((rig_point[0] - foot_x) * s, (rig_point[1] - foot_y) * s - gap)
            widget = transform.map(image)
            back = w._to_rig(widget)
            assert np.allclose(back, rig_point, atol=1e-6), (rig_point, back)
    w.close()


def test_zones_are_found_by_v3_hit_test_not_v2_rectangles(qapp):
    w, t, _ = window(qapp)
    kinds = {find(w, k): k for k in ("cheek", "crown", "belly")}
    assert len(kinds) == 3
    assert w._hit_zone(QPoint(0, 0)) == "outside"
    assert w._hit_zone(find(w, "crown")) == "body"  # V2 的“头”分区不再触发 V2 摸头
    assert not hasattr(w, "_is_head")  # V2 的“头”分区判断已删除
    w.close()


# ---- 捏脸 ----
def test_cheek_pinch_emits_pull_once_then_release_and_never_clicked(qapp):
    w, t, spy = window(qapp)
    start = find(w, "cheek")
    press(w, start)
    assert spy.gesture == []                        # 还没横向拉：不算捏
    move(w, start + QPoint(10, 0))
    move(w, start + QPoint(18, 0))
    assert spy.gesture == ["cheek_pull"]
    assert w._v3_animator.reaction.active and w._v3_animator.dragging
    assert not hasattr(w, "_pose")                  # 不用 V2 的脸颊精灵
    run_for(w, t, .2)
    assert w._timer.interval() == 16                # 互动期间 60 FPS
    release(w, start + QPoint(18, 0))
    assert spy.gesture == ["cheek_pull", "cheek_release"]
    assert spy.clicked == [] and spy.drags == []
    assert not w._v3_animator.dragging
    assert_clean(w)
    w.close()


def test_cheek_click_without_pulling_is_an_ordinary_click(qapp):
    w, t, spy = window(qapp)
    pos = find(w, "cheek")
    click(w, pos)
    assert spy.clicked == [1] and spy.gesture == []
    assert not w._v3_animator.reaction.active
    assert_clean(w)
    w.close()


@pytest.mark.parametrize("dx", [90, -90, 300])
def test_pinch_pulled_sideways_far_stays_a_pinch_and_never_moves_the_window(qapp, dx):
    w, t, spy = window(qapp)
    w.move(300, 200)
    start = find(w, "cheek")
    g0 = w.mapToGlobal(start)
    origin = w.pos()
    press(w, start)
    gmove(w, g0, dx // 4, 0)
    gmove(w, g0, dx, 0)
    assert not w.is_dragging and not w.lifting and spy.drags == []
    assert w.pos() == origin
    assert w._v3_animator.dragging and spy.gesture.count("cheek_pull") == 1
    grelease(w, g0, dx, 0)
    assert spy.gesture.count("cheek_release") == 1 and spy.clicked == []
    assert spy.ignored == []
    assert_clean(w)
    w.close()


# ---- 摸头 / 敲头 ----
def test_crown_wipe_emits_patted_per_40px_and_no_click_or_knock(qapp):
    w, t, spy = window(qapp)
    start = find(w, "crown")
    press(w, start)
    for step in range(1, 11):
        move(w, start + QPoint(step * 10, 0))
        t[0] += .016
    assert len(spy.patted) == 2                    # 100px / 40px
    assert w._v3_animator.head_touch.kind == "pat"
    release(w, start + QPoint(100, 0))
    assert spy.clicked == [] and spy.knocked == [] and spy.drags == []
    assert w._v3_animator.head_touch.released_at is not None
    assert_clean(w)
    w.close()


def test_crown_click_knocks_without_poke_and_third_knock_protests(qapp):
    w, t, spy = window(qapp)
    pos = find(w, "crown")
    click(w, pos)
    assert spy.knocked == [False] and spy.clicked == []
    assert w._v3_animator.head_touch.kind == "knock"
    assert_clean(w)
    run_for(w, t, .3)
    click(w, pos)
    run_for(w, t, .3)
    click(w, pos)
    assert spy.knocked == [False, False, True]
    assert spy.clicked == [] and spy.patted == []
    w.close()


def test_crown_double_click_is_two_knocks_not_a_poke(qapp):
    w, t, spy = window(qapp)
    pos = find(w, "crown")
    QTest.mouseClick(w, Qt.LeftButton, Qt.NoModifier, pos)
    QTest.mouseDClick(w, Qt.LeftButton, Qt.NoModifier, pos)
    QTest.mouseRelease(w, Qt.LeftButton, Qt.NoModifier, pos)
    assert spy.clicked == [] and len(spy.knocked) >= 1
    assert_clean(w)
    w.close()


# ---- 挠痒 ----
def rub(w, t, start, seconds, step=.15):
    """左右揉：每 step 秒换向一次，每次 12px。"""
    end = t[0] + seconds
    x, sign = 0, 1
    while t[0] < end:
        x += sign * 12
        sign = -sign
        move(w, start + QPoint(x, 0))
        t[0] += step
        w.advance_to(t[0])


def test_belly_rub_starts_tickle_repeats_every_4s_and_ends_after_1s_idle(qapp):
    w, t, spy = window(qapp)
    start = find(w, "belly")
    press(w, start)
    assert spy.gesture == ["belly"]
    rub(w, t, start, 1.2)
    assert spy.gesture.count("tickle") == 1 and w._v3_animator.tickle.active
    assert w.motion_active
    rub(w, t, start, 4.5)
    assert spy.gesture.count("tickle") >= 2         # 每 4 秒再说一次
    last = w._v3_tickle_last                 # 最后一次揉动的时刻
    t[0] = last + .95
    w.advance_to(t[0])
    assert "tickle_end" not in spy.gesture
    t[0] = last + 1.05
    w.advance_to(t[0])
    assert spy.gesture.count("tickle_end") == 1
    release(w, start)
    assert spy.clicked == [] and spy.drags == []
    assert not w.motion_active
    assert_clean(w)
    w.close()


def test_release_while_tickling_still_ends_with_tickle_end_after_1s(qapp):
    w, t, spy = window(qapp)
    start = find(w, "belly")
    press(w, start)
    rub(w, t, start, 1.5)
    release(w, start)
    assert "tickle_end" not in spy.gesture
    run_for(w, t, 1.3)
    assert spy.gesture.count("tickle_end") == 1
    w.close()


def test_belly_single_click_is_an_ordinary_poke_and_never_tickles(qapp):
    w, t, spy = window(qapp)
    click(w, find(w, "belly"))
    assert spy.clicked == [1]
    assert spy.gesture == ["belly"]                 # 按下时的静默事件
    assert w._v3_tickle_start is None
    assert_clean(w)
    w.close()


def test_belly_dragged_without_rubbing_does_not_move_the_window_and_hints(qapp):
    w, t, spy = window(qapp)
    w.move(300, 200)
    start = find(w, "belly")
    g0 = w.mapToGlobal(start)
    origin = w.pos()
    press(w, start)
    gmove(w, g0, 0, 60)
    assert not w.is_dragging and w.pos() == origin and spy.drags == []
    assert spy.ignored == [1]
    gmove(w, g0, 0, 80)
    assert spy.ignored == [1]                       # 每次按下最多提示一次
    grelease(w, g0, 0, 80)
    assert "tickle" not in spy.gesture and spy.clicked == []
    assert_clean(w)
    w.close()


def test_belly_rubbing_does_not_hint(qapp):
    w, t, spy = window(qapp)
    start = find(w, "belly")
    g0 = w.mapToGlobal(start)
    press(w, start)
    for i in range(14):
        gmove(w, g0, 14 if i % 2 else -14, 0)
        t[0] += .02
    assert "tickle" in spy.gesture and spy.ignored == []
    grelease(w, g0, 0, 0)
    w.close()


def test_belly_pause_keeps_the_gesture_and_rubbing_again_resumes_tickle(qapp):
    w, t, spy = window(qapp)
    start = find(w, "belly")
    g0 = w.mapToGlobal(start)
    press(w, start)
    for i in range(14):
        gmove(w, g0, 14 if i % 2 else -14, 0)
        t[0] += .02
    assert w._v3_animator.tickle.active
    w.advance_to(t[0])
    assert w._v3_gesture == "belly" and not w.is_dragging
    grelease(w, g0, 0, 0)
    w.close()


# ---- 其他部位保持 V2 规则 ----
@pytest.mark.parametrize("kind", ["body", "face", "head"])
def test_other_parts_still_poke_on_click_but_cannot_drag_the_window(qapp, kind):
    w, t, spy = window(qapp)
    w.move(300, 200)
    try:
        pos = find(w, kind)
    except AssertionError:
        pytest.skip(f"this rig has no {kind} hit in the grid")
    click(w, pos)
    assert spy.clicked == [1] and spy.gesture == [] and spy.knocked == []
    origin = w.pos()
    g0 = w.mapToGlobal(pos)
    press(w, pos)
    gmove(w, g0, 40, 0)
    assert not w.is_dragging and w.pos() == origin and spy.drags == []
    assert spy.ignored == [1]
    gmove(w, g0, 80, 10)
    assert spy.ignored == [1]
    grelease(w, g0, 80, 10)
    assert spy.clicked == [1]                       # 被吃掉：不戳、不拖
    assert spy.finished == []
    assert_clean(w)
    w.close()


def test_small_wobble_on_the_body_is_still_a_click_and_never_hints(qapp):
    w, t, spy = window(qapp)
    pos = find(w, "body")
    g0 = w.mapToGlobal(pos)
    press(w, pos)
    gmove(w, g0, 3, 2)
    grelease(w, g0, 3, 2)
    assert spy.clicked == [1] and spy.ignored == []
    w.close()


def test_focus_out_releases_every_hold(qapp):
    w, t, spy = window(qapp)
    start = find(w, "cheek")
    press(w, start)
    move(w, start + QPoint(20, 0))
    assert w._v3_animator.dragging
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QFocusEvent
    w.focusOutEvent(QFocusEvent(QEvent.FocusOut))
    assert not w._v3_animator.dragging and w._v3_gesture is None
    release(w, start + QPoint(20, 0))
    assert_clean(w)
    w.close()


def test_hover_cursor_is_open_hand_on_gesture_zones_only(qapp):
    w, t, _ = window(qapp)
    for kind in ("cheek", "crown", "belly"):
        w._update_hover_cursor(find(w, kind))
        assert w.cursor().shape() == Qt.OpenHandCursor
    w._update_hover_cursor(QPoint(0, 0))
    assert w.cursor().shape() != Qt.OpenHandCursor
    w.close()


def test_mouse_handler_cost_stays_far_below_the_frame_budget(qapp):
    import time
    w, t, _ = window(qapp)
    start = find(w, "cheek")
    press(w, start)
    move(w, start + QPoint(10, 0))
    times = []
    for i in range(60):
        t0 = time.perf_counter()
        w.mouseMoveEvent(_move_event(w, start + QPoint(12 + i % 20, 0)))
        times.append((time.perf_counter() - t0) * 1000)
    release(w, start + QPoint(20, 0))
    assert np.percentile(times, 95) < 8.0, np.percentile(times, 95)  # 含 refresh；单独的命中判断见 perf 记录
    hit_times = []
    for i in range(60):
        t0 = time.perf_counter()
        w._v3_hit(QPointF(find(w, "crown")) + QPointF(i % 7, 0))
        hit_times.append((time.perf_counter() - t0) * 1000)
    # 单独跑 P95 约 0.3～0.5ms；长时间全量跑时机器有负载，曾到 1.57ms。
    # 线放到 3ms：仍不到 60 FPS 一帧（16ms）的五分之一，真退化（例如每次命中都
    # 重新合成图层，约 10ms 以上）照样会抓到。
    assert np.percentile(hit_times, 95) < 3.0, np.percentile(hit_times, 95)
    w.close()


def _move_event(w, pos):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent
    return QMouseEvent(QEvent.MouseMove, QPointF(pos), QPointF(w.mapToGlobal(pos)),
                       Qt.NoButton, Qt.LeftButton, Qt.NoModifier)


# ---- 与控制器、台词、好感衔接 ----
def test_combo_line_replaces_the_pull_line_from_the_third_pull_within_10s(env):  # noqa: F811
    lines = env.ctl.lines._lines
    env.win.gesture.emit("cheek_pull")
    assert env.said[-1] in lines["cheek_pull"]
    env.advance(5)
    env.win.gesture.emit("cheek_pull")
    env.advance(4.1)                          # 第 3 次：与第 1 次相隔 9.1 秒，仍在 10 秒内
    env.win.gesture.emit("cheek_pull")
    assert env.said[-1] in lines["cheek_pull_combo"]
    env.advance(11)
    env.win.gesture.emit("cheek_pull")        # 10 秒窗口里只剩这 1 次：回到普通台词
    assert env.said[-1] in lines["cheek_pull"]
    assert env.data.affection == env.data.stats["pats"] == env.state._poke_count == 0


def test_combo_does_not_fire_when_pulls_are_spread_out(env):  # noqa: F811
    lines = env.ctl.lines._lines
    for _ in range(4):
        env.win.gesture.emit("cheek_pull")
        assert env.said[-1] in lines["cheek_pull"]
        env.advance(6)


def test_knock_lines_use_low_priority_cooldown_and_protest_line_is_not_blocked(env):  # noqa: F811
    lines = env.ctl.lines._lines
    env.ctl._on_knock(False)
    assert env.said[-1] in lines["head_knock"]
    count = len(env.said)
    env.advance(1)
    env.ctl._on_knock(False)                    # 4 秒冷却内：不说
    assert len(env.said) == count
    env.ctl._on_knock(True)                     # 第一句还在最短显示时间内：低优先级台词不互相打断
    assert len(env.said) == count
    env.advance(1.6)                            # 第一句已显示满 2.5 秒；抗议是另一类，不受 head_knock 冷却影响
    env.ctl._on_knock(True)
    assert env.said[-1] in lines["head_knock_stop"]
    assert env.data.affection == env.data.stats["pats"] == env.state._poke_count == 0


def test_knock_consumes_a_waiting_weekly_offer_before_speaking(env, monkeypatch):  # noqa: F811
    opened = []
    monkeypatch.setattr(env.ctl, "open_weekly", lambda *a: opened.append(a))
    env.ctl._weekly_offer = object()
    env.ctl._on_knock(False)
    assert opened and env.ctl._weekly_offer is None
    assert env.said == []


def test_pat_signal_still_gives_affection_and_pat_count(env):  # noqa: F811
    env.win.patted.emit()
    assert env.state.save.affection == 1 and env.state.save.stats["pats"] == 1


@pytest.mark.parametrize("lang", ["zh", "en", "ja"])
def test_new_line_keys_exist_in_every_language(lang):
    lines = json.loads((LINES_DIR / f"{lang}.json").read_text(encoding="utf-8"))["lines"]
    assert len(lines["cheek_pull_combo"]) == 3 and len(set(lines["cheek_pull_combo"])) == 3
    assert len(lines["head_knock"]) == 2 and len(lines["head_knock_stop"]) == 2


# ---- 拎起摇晃落地：遮罩不能裁掉正在显示的像素 ----
def _clipped(w):
    """当前帧里有颜色、却在窗口遮罩之外的像素数（隔 3 个点抽样）。"""
    from PySide6.QtGui import QImage, QPainter
    sprite = QImage(w.size(), QImage.Format_ARGB32_Premultiplied)
    sprite.fill(0)
    p = QPainter(sprite)
    p.setRenderHints(QPainter.SmoothPixmapTransform | QPainter.Antialiasing)
    w._draw_sprite(p, w._frame)
    p.end()
    alpha = np.frombuffer(sprite.constBits(), np.uint8).reshape(
        sprite.height(), sprite.bytesPerLine())[:, 3:sprite.width() * 4:4]
    region = w.mask()
    return sum(1 for y, x in np.argwhere(alpha > 24)[::3] if not region.contains(QPoint(int(x), int(y))))


@pytest.mark.parametrize("height", (160, 320))
def test_lift_shake_and_landing_never_clip_visible_pixels(qapp, height):  # noqa: F811
    w, t, _ = window(qapp, height)
    w.show()
    start = find(w, "body")
    press(w, start)
    frames = 0
    for i in range(30):
        pos = start + QPoint(60 if i % 2 else -60, -80)
        move(w, pos)
        t[0] += w._timer.interval() / 1000
        w.advance_to(t[0])
        frames += 1
        assert _clipped(w) == 0, ("shake", i)
    release(w, pos)
    if not w.is_falling:
        w.start_fall()
    for i in range(400):
        t[0] += w._timer.interval() / 1000
        w.advance_to(t[0])
        frames += 1
        assert _clipped(w) == 0, ("land", i, round(w._frame.sy, 3))
        if not w.is_falling and i > 60 and w._frame.sy == 1.0 and w._frame.angle == 0.0:
            break
    assert frames > 60


def test_resting_idle_does_not_rebuild_masks_every_frame(qapp):  # noqa: F811
    w, t, _ = window(qapp, 200)
    before = w.v3_stats["masks"]
    end = t[0] + 4.0
    while t[0] < end:
        t[0] += w._timer.interval() / 1000
        w.advance_to(t[0])
    assert (w.v3_stats["masks"] - before) / 4.0 <= 10.5


# ---- S4：拎脸颊移动真实窗口 ----
def _lift_start(qapp, height=320):
    w, t, spy = window(qapp, height)
    w.move(300, 300)
    start = find(w, "cheek")
    g0 = w.mapToGlobal(start)
    press(w, start)
    return w, t, spy, g0


def _step(w, t, seconds=.016):
    t[0] += seconds
    w.advance_to(t[0])


def test_cheek_up_drag_lifts_the_real_window_and_a_slow_release_stays_put(qapp):
    w, t, spy, g0 = _lift_start(qapp)
    origin = w.pos()
    gmove(w, g0, 0, -8)                                # 没到 12px：还不是拎起
    assert not w.lifting and not w.is_dragging and spy.drags == []
    gmove(w, g0, 0, -20)
    assert w.lifting and w.is_dragging and spy.drags == [1]
    assert w.pos().y() == origin.y() - 20
    assert w._v3_animator.lift.held
    assert "cheek_pull" not in spy.gesture
    for i in range(1, 7):
        _step(w, t)
        gmove(w, g0, 0, -20 - i * 10)
    assert w.pos().y() == origin.y() - 80
    t[0] += 1.0                                        # 停住 1 秒再松手：速度 ≈ 0
    w.advance_to(t[0])
    grelease(w, g0, 0, -80)
    assert not w.lifting and not w.is_falling
    assert spy.finished == [1]
    assert "cheek_release" not in spy.gesture and spy.clicked == []
    assert w.pos().y() < origin.y()                    # 原地停留，不回原站位
    assert w._v3_animator.lift.released_at is not None
    assert_clean(w)
    w.close()


@pytest.mark.parametrize("dx,dy,lifts", [(0, -13, True), (0, -12, False), (10, -13, True),
                                          (40, -30, False), (40, -49, True), (-40, -49, True),
                                          (0, 30, False)])
def test_lift_needs_more_than_12px_up_and_1_2x_the_sideways_move(qapp, dx, dy, lifts):
    w, t, spy, g0 = _lift_start(qapp, 200)
    gmove(w, g0, dx, dy)
    assert w.lifting == lifts and (spy.drags == [1]) == lifts
    grelease(w, g0, dx, dy)
    w.close()


def test_fast_upward_fling_falls_after_release(qapp):
    w, t, spy, g0 = _lift_start(qapp)
    gmove(w, g0, 0, -20)
    for i in range(1, 6):
        t[0] += .016
        gmove(w, g0, 0, -20 - i * 40)                  # 2500 px/s
    grelease(w, g0, 0, -220)
    assert w.is_falling and spy.finished == []
    for _ in range(400):
        _step(w, t)
        if not w.is_falling:
            break
    assert not w.is_falling and spy.finished == [1]
    w.close()


def test_catching_a_falling_pet_by_the_cheek_can_lift_it_but_other_parts_cannot(qapp):
    w, t, spy = window(qapp, 200)
    w.move(300, 200)
    w.release_to_taskbar = True                        # 菜单开关开启时按原重力继续落
    cheek, body = find(w, "cheek"), find(w, "body")
    w.start_fall()
    g0 = w.mapToGlobal(body)
    origin_y = w.pos().y()
    press(w, body)
    gmove(w, g0, 60, -60)
    assert not w.is_dragging and w.pos().y() == origin_y and spy.drags == []
    grelease(w, g0, 60, -60)
    assert w.is_falling and spy.clicked == []          # 接住后松手：继续下落，没有戳
    w.start_fall()
    _step(w, t)
    g1 = w.mapToGlobal(cheek)
    press(w, cheek)
    assert not w.is_falling
    gmove(w, g1, 0, -40)
    assert w.lifting and w.is_dragging
    t[0] += 1.0
    w.advance_to(t[0])
    grelease(w, g1, 0, -40)
    w.close()


def test_lift_keeps_the_art_still_and_tilts_with_speed_without_the_v2_tilt(qapp):
    w, t, spy, g0 = _lift_start(qapp)
    gmove(w, g0, 0, -30)
    assert w.lifting
    a = w._v3_animator
    rolls, angles = [], []
    for i in range(30):
        t[0] += .016
        gmove(w, g0, int(40 * math.sin(i / 3)), -30)
        w.advance_to(t[0])
        assert tuple(a.pose.root_offset) == (0.0, 0.0)
        rolls.append(a.pose.root_roll)
        angles.append(w._frame.angle)
    assert max(abs(r) for r in rolls) > 0.5            # 速度带出的 V3 倾斜
    assert max(abs(x) for x in angles) < 1e-6          # V2 倾斜没有叠加
    grelease(w, g0, 0, -30)
    w.close()


def test_three_shakes_make_the_lift_dizzy_and_report_shaken_once(qapp):
    w, t, spy, g0 = _lift_start(qapp, 320)
    gmove(w, g0, 0, -30)
    for i in range(8):                                 # 来回 ±40px（逻辑）
        t[0] += .1
        gmove(w, g0, 40 if i % 2 else -40, -30)
        w.advance_to(t[0])
    assert w._v3_animator.lift.dizzy
    t[0] += .5
    w.advance_to(t[0])
    grelease(w, g0, 0, -30)
    assert w.consume_shaken() is True
    assert w.consume_shaken() is False
    w.close()


def test_a_calm_lift_is_not_shaken(qapp):
    w, t, spy, g0 = _lift_start(qapp)
    gmove(w, g0, 0, -30)
    for i in range(10):
        t[0] += .1
        gmove(w, g0, 0, -30 - i * 3)
        w.advance_to(t[0])
    t[0] += 1
    w.advance_to(t[0])
    grelease(w, g0, 0, -60)
    assert w.consume_shaken() is False
    w.close()


def test_focus_out_while_lifting_releases_the_lift(qapp):
    w, t, spy, g0 = _lift_start(qapp)
    gmove(w, g0, 0, -30)
    assert w.lifting
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QFocusEvent
    w.focusOutEvent(QFocusEvent(QEvent.FocusOut))
    assert not w.lifting and w._v3_animator.lift.released_at is not None
    t[0] += 1
    w.advance_to(t[0])
    grelease(w, g0, 0, -30)                            # 鼠标松开后父类照常收尾
    assert spy.finished == [1]
    w.close()


def test_lift_shake_and_landing_never_clip_visible_pixels_with_the_real_lift(qapp):  # noqa: F811
    w, t, spy, g0 = _lift_start(qapp, 320)
    gmove(w, g0, 0, -20)
    assert w.lifting
    for i in range(40):
        t[0] += .016
        gmove(w, g0, 70 if i % 2 else -70, -20 - i)
        w.advance_to(t[0])
        assert _clipped(w) == 0, ("lift", i)
    grelease(w, g0, 0, -60)
    for i in range(500):
        _step(w, t)
        assert _clipped(w) == 0, ("after", i)
        if not w.is_falling and w._v3_animator.lift.active is False and i > 30:
            break
    w.close()


def test_v3_lift_hint_and_cheek_lift_lines_exist_in_every_language():
    for lang in ("zh", "en", "ja"):
        lines = json.loads((LINES_DIR / f"{lang}.json").read_text(encoding="utf-8"))["lines"]
        assert len(lines["cheek_lift"]) == 3 and len(set(lines["cheek_lift"])) == 3
        assert len(lines["v3_lift_hint"]) == 1
    zh = json.loads((LINES_DIR / "zh.json").read_text(encoding="utf-8"))["lines"]
    en = json.loads((LINES_DIR / "en.json").read_text(encoding="utf-8"))["lines"]
    ja = json.loads((LINES_DIR / "ja.json").read_text(encoding="utf-8"))["lines"]
    assert zh["cheek_lift"][0] == "脸、脸不是把手啦！"
    assert en["cheek_lift"][0] == "My cheek is NOT a handle!"
    assert ja["cheek_lift"][0] == "ほっぺは取っ手じゃないってば！"


# ---- S4：控制器 ----
def test_drag_start_uses_cheek_lift_line_only_when_lifting(env):  # noqa: F811
    lines = env.ctl.lines._lines
    env.win._v3_lifting = True  # lifting 是只读属性，直接置内部状态
    env.win.drag_started.emit()
    assert env.said[-1] in lines["cheek_lift"]
    env.win.drag_finished.emit()
    env.advance(6)
    env.win._v3_lifting = False
    env.win.drag_started.emit()
    assert env.said[-1] in lines["drag"]


def test_shaken_lift_ends_with_the_dizzy_line(env):  # noqa: F811
    lines = env.ctl.lines._lines
    env.win.consume_shaken = lambda: True
    env.win.drag_started.emit()
    env.advance(5)                                     # 越过 LOW 类别 4 秒冷却（与 V2 相同）
    env.win.drag_finished.emit()
    assert env.said[-1] in lines["dizzy"]


def test_ignored_drag_hint_has_its_own_60s_cooldown(env):  # noqa: F811
    lines = env.ctl.lines._lines
    env.ctl._on_drag_ignored()
    assert env.said[-1] in lines["v3_lift_hint"] and len(env.said) == 1
    env.advance(30)
    env.ctl._on_drag_ignored()
    assert len(env.said) == 1                          # 60 秒内不重复
    env.advance(31)
    env.ctl._on_drag_ignored()
    assert len(env.said) == 2


def test_first_start_hint_is_remembered_only_after_it_is_really_said(env, monkeypatch):  # noqa: F811
    import shion.controller as C
    timers = []
    monkeypatch.setattr(C.QTimer, "singleShot", staticmethod(lambda ms, fn: timers.append((ms, fn))))
    env.ctl.say("别的话", priority=C.Priority.MEDIUM, category="startup")
    assert env.said == ["别的话"]
    env.ctl.arm_lift_hint()
    assert timers[-1][0] == env.ctl.LIFT_HINT_DELAY_MS
    timers.pop()[1]()                                  # 10 秒后：气泡里的中优先级台词还在
    assert not env.state.save.v3_lift_hint_shown
    assert timers and timers[-1][0] == env.ctl.LIFT_HINT_RETRY_MS
    env.advance(10)
    timers.pop()[1]()
    assert env.said[-1] in env.ctl.lines._lines["v3_lift_hint"]
    assert env.state.save.v3_lift_hint_shown
    assert not timers
    env.ctl.arm_lift_hint()                            # 已提示过：不再安排
    assert not timers


def test_lift_hint_flag_survives_save_and_old_saves_default_to_false():
    from shion.state import SaveData
    d = SaveData.from_dict({})
    assert d.v3_lift_hint_shown is False
    d.v3_lift_hint_shown = True
    assert SaveData.from_dict(d.to_dict()).v3_lift_hint_shown is True
    assert SaveData.from_dict({"v3_lift_hint_shown": "yes"}).v3_lift_hint_shown is False


def test_mouse_moves_never_render_a_frame_each_the_timer_does(qapp):  # noqa: F811
    """鼠标一秒几百个移动事件：不能每个事件渲染一帧（125Hz 摸头曾每帧 13ms、250Hz 27ms）。"""
    for kind, move_to in (("crown", lambda i: int(40 * math.sin(i / 5))),
                          ("cheek", lambda i: 12 + i % 30)):
        w, t, spy = window(qapp, 260)
        start = find(w, kind)
        g0 = w.mapToGlobal(start)
        press(w, start)
        before = w.v3_stats["rendered"]
        for i in range(400):
            t[0] += .001
            gmove(w, g0, move_to(i), 0)
        assert w.v3_stats["rendered"] == before, kind
        # 定时器照常把动画画出来。后台预热占锁时这一帧会先推迟（S7 第 6 条），
        # 所以按真实帧间隔推进；机器满载时后台更慢，最多等 3 秒。
        deadline = time.perf_counter() + 3.0
        while w.v3_stats["rendered"] == before and time.perf_counter() < deadline:
            time.sleep(.016)
            t[0] += .016
            w.advance_to(t[0])
        assert w.v3_stats["rendered"] > before, f"{kind} {dict(w.v3_stats)} {w._v3_settings.expression} key={w._v3_key!r:.200}"
        grelease(w, g0, 0, 0)
        w.close()


# ---- 摸头/敲头卡顿的回归（真实窗口里测出来的三个原因）----
def _wait_prewarm(w, seconds=60):
    import time
    end = time.time() + seconds
    while w._v3_prewarmer.pending and time.time() < end:
        w._v3_prewarmer.collect()
        time.sleep(.05)
    assert not w._v3_prewarmer.pending


def test_cheek_prepare_of_a_finished_expression_never_waits_for_the_background_lock(qapp):  # noqa: F811
    import threading
    import time
    w, t, spy = window(qapp, 200)
    _wait_prewarm(w)
    surface = w._v3_renderer.head_surface
    assert w._v3_settings.expression in surface.cheek.backgrounds
    held, release_it = threading.Event(), threading.Event()

    def hog():                                          # 假装后台正在合成眨眼帧
        with surface._v3_lock:
            held.set()
            release_it.wait(5)

    thread = threading.Thread(target=hog, daemon=True)
    thread.start()
    assert held.wait(2)
    t0 = time.perf_counter()
    surface.cheek.prepare(surface, w._v3_settings)
    waited = time.perf_counter() - t0
    release_it.set()
    thread.join(2)
    assert waited < 0.02, waited
    w.close()


def test_interaction_cancels_queued_blink_prewarm_and_idle_requests_it_again():
    from concurrent.futures import Future
    from types import SimpleNamespace
    from shion.v3_prewarm import BLINK_LEVELS, Prewarmer

    class Queue:
        def __init__(self):
            self.futures = []

        def submit(self, fn, *args):
            future = Future()
            self.futures.append(future)
            return future

    surface = SimpleNamespace(
        frames={}, _compose_image=lambda *a, **k: None,
        cheek=SimpleNamespace(config=None, backgrounds={}, prepare=lambda *a, **k: None),
        reaction_face=SimpleNamespace(patch=lambda *a, **k: None))
    executor = Queue()
    prewarmer = Prewarmer(SimpleNamespace(head_surface=surface), SimpleNamespace(), executor=executor)
    # settings 只用于 replace()，换成 dataclass
    from dataclasses import dataclass

    @dataclass
    class S:
        expression: str = "happy"

    prewarmer.settings = S()
    prewarmer.request("happy")                          # 睁眼帧：互动时不取消
    prewarmer.request_blinks("happy")
    queued = len(prewarmer.pending)
    assert queued == len(BLINK_LEVELS)                  # 睁眼 1.0 已在 BLINK_LEVELS 里，去重后一样多
    prewarmer.cancel_blinks()
    assert all(key[1] == 1.0 for key in prewarmer.pending) and len(prewarmer.pending) == 1
    prewarmer.request_blinks("happy")                   # 互动结束：补回来
    assert len(prewarmer.pending) == queued


def test_stop_motion_during_a_gesture_does_not_render_an_extra_frame(qapp):  # noqa: F811
    w, t, spy = window(qapp, 200)
    start = find(w, "crown")
    press(w, start)
    before = w.v3_stats["refresh"]
    w.stop_motion()                                     # 摸头每 40px 控制器会调一次
    assert w.v3_stats["refresh"] == before
    release(w, start + QPoint(30, 0))
    before = w.v3_stats["refresh"]
    w.stop_motion()
    assert w.v3_stats["refresh"] == before + 1          # 没有手势时仍照旧立刻刷新
    w.close()


def test_reaction_faces_do_not_blink_with_an_uncomputed_patch(qapp):  # noqa: F811
    w, t, spy = window(qapp, 260)
    _wait_prewarm(w)
    reaction = w._v3_renderer.head_surface.reaction_face
    calls = []
    original = reaction.patch

    def spy_patch(face, eye_scale=1., erase=False):
        if eye_scale != 1. and not erase:
            calls.append((face, eye_scale))
        return original(face, eye_scale, erase)

    reaction.patch = spy_patch
    start = find(w, "crown")
    g0 = w.mapToGlobal(start)
    press(w, start)
    for i in range(150):
        t[0] += .016
        w._v3_animator.blink_start = w._v3_animator.time - .05   # 一直在眨眼的中途
        gmove(w, g0, 25 if (i // 6) % 2 else -25, 0)
        w.advance_to(t[0])
    grelease(w, g0, 0, 0)
    assert calls == []
    w.close()


def test_pat_in_the_happy_state_does_not_rebuild_the_mask_every_frame(qapp):  # noqa: F811
    """摸头会让状态机进入 happy（V2 帧有轻微弹动）：遮罩（原生 setMask 约 4ms/次）不能每帧重建。"""
    w, t, spy = window(qapp, 260)
    w.set_state("happy", animate=False)
    start = find(w, "crown")
    g0 = w.mapToGlobal(start)
    press(w, start)
    before = w.v3_stats["masks"]
    for i in range(190):                                # ≈3 秒
        t[0] += .016
        gmove(w, g0, 25 if (i // 6) % 2 else -25, 0)
        w.advance_to(t[0])
    per_second = (w.v3_stats["masks"] - before) / 3.0
    grelease(w, g0, 0, 0)
    assert per_second <= 16, per_second            # 不是每帧一次（修复前约 60 次/秒）
    w.close()
