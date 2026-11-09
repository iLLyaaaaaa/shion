"""S3：V3 窗口的捏脸 / 敲头 / 摸头 / 挠痒手势，以及与台词、好感的衔接。

离屏、假时钟、真实 Qt 鼠标事件；不依赖真人鼠标。
"""
import json
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
        w.gesture.connect(self.gesture.append)
        w.patted.connect(lambda: self.patted.append(1))
        w.clicked.connect(lambda: self.clicked.append(1))
        w.knocked.connect(self.knocked.append)
        w.drag_started.connect(lambda: self.drags.append(1))


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


def click(w, pos):
    press(w, pos)
    release(w, pos)


def assert_clean(w):
    assert not w.is_pressed and not w._pat_mode and not w._cheek_mode and not w._belly_mode
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
    assert not w._is_head(find(w, "crown"))
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
    assert w._pose is None                          # 不用 V2 的脸颊精灵
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


@pytest.mark.parametrize("delta", [QPoint(90, 0), QPoint(-90, 0), QPoint(0, -90)])
def test_pinch_dragged_past_80px_becomes_window_drag_without_release_line(qapp, delta):
    w, t, spy = window(qapp)
    start = find(w, "cheek")
    origin = w.pos()
    press(w, start)
    move(w, start + QPoint(20, 0) if delta.x() >= 0 else start - QPoint(20, 0))
    move(w, start + delta)
    assert w.is_dragging and spy.drags == [1]
    assert w.pos() != origin
    assert not w._v3_animator.dragging
    release(w, start + delta)
    assert "cheek_release" not in spy.gesture and spy.clicked == []
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


def test_belly_dragged_without_rubbing_becomes_window_drag(qapp):
    w, t, spy = window(qapp)
    start = find(w, "belly")
    origin = w.pos()
    press(w, start)
    move(w, start + QPoint(0, 60))
    assert w.is_dragging and w.pos() != origin
    release(w, start + QPoint(0, 60))
    assert "tickle" not in spy.gesture and spy.clicked == []
    assert_clean(w)
    w.close()


# ---- 其他部位保持 V2 规则 ----
@pytest.mark.parametrize("kind", ["body", "face", "head"])
def test_other_parts_click_like_v2_and_drag_moves_window(qapp, kind):
    w, t, spy = window(qapp)
    try:
        pos = find(w, kind)
    except AssertionError:
        pytest.skip(f"this rig has no {kind} hit in the grid")
    click(w, pos)
    assert spy.clicked == [1] and spy.gesture == [] and spy.knocked == []
    origin = w.pos()
    press(w, pos)
    move(w, pos + QPoint(40, 0))
    assert w.is_dragging and w.pos() != origin
    release(w, pos + QPoint(40, 0))
    assert_clean(w)
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
    assert np.percentile(hit_times, 95) < 1.5, np.percentile(hit_times, 95)
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
