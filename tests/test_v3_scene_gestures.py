"""S9 第 4 步：姿势变体（collapse / bed / desk）里的手势、锚点、睡觉 Z、换边冻结。

规则（轻互动）：拎起 → 立刻切回站姿；摸头 → 整图轻晃 ≤1°；敲头 → 下压 ≤2% + 金星；
捏脸、挠痒 → 不响应；点身体 → 戳；点家具 → 点穿。
"""
import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF

from shion import v3_scene as vs
from shion.v3_window import MARGIN_X
from tests.test_v3_display import make, qapp  # noqa: F401  (qapp 是 fixture)
from tests.test_v3_gestures import Spy, click, gmove, grelease, move, press, release
from tests.test_v3_scene_window import scene_px, settle
from tests.test_v3_state_pose import run

SCENE_STATES = ("collapse", "bed", "desk")


@pytest.fixture(autouse=True)
def no_background_scene_jobs(monkeypatch):
    from shion.v3_window import V3PetWindow
    monkeypatch.setattr(V3PetWindow, "_v3_scene_prewarm", lambda self: None)


@pytest.fixture
def scene_window(qapp):  # noqa: F811
    made = []

    def build(state, height=260, dpr=1.0, auto_side=False, x=300, scene=True):
        w, t = make(qapp, height, dpr)
        w.auto_side = auto_side
        w.set_state("idle", animate=False)
        w.move(x, 200)
        w.show()
        run(w, t, 0.3)
        settle(w, t, state, 0.8)
        made.append(w)
        assert (w._v3_scene_w == 1.0) == scene
        return w, t, Spy(w)
    yield build
    for w in made:
        w.close()
        w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


_POINTS: dict = {}


def find(w, state, kind):
    """窗口里命中为 kind 的点里，最靠近这些点重心的那个。"""
    key = (state, w.height(), w._v3_dpr, kind)
    if key not in _POINTS:
        pts = [(x, y) for y in range(0, w.height(), 2) for x in range(0, w.width(), 2)
               if w._v3_hit(QPointF(x, y))[0] == kind]
        assert pts, (state, kind)
        cx, cy = np.mean(pts, axis=0)
        _POINTS[key] = QPoint(*min(pts, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2))
    return _POINTS[key]


def step(w, t, seconds=.016):
    t[0] += seconds
    w.advance_to(t[0])


def far_furniture(w, state, n=12):
    """离角色远的家具像素 → 窗口坐标点。"""
    from scipy import ndimage as nd
    scene = w._v3_scenes[state]
    a = vs.load_arrays(scene, 0.25)
    far = (a["furniture"][..., 3] >= 250) & ~nd.binary_dilation(a["alpha"] > 0, iterations=24)
    ys, xs = np.nonzero(far)
    pick = np.random.default_rng(3).choice(len(xs), min(n, len(xs)), replace=False)
    return [QPoint(*map(round, scene_px(w, scene, xs[i] / a["scale"] - a["pad"], ys[i] / a["scale"] - a["pad"])))
            for i in pick]


# ---- 命中 ----
@pytest.mark.parametrize("state", SCENE_STATES)
def test_zones_are_found_by_the_scene_hit_test(qapp, scene_window, state):  # noqa: F811
    w, t, _ = scene_window(state)
    assert {find(w, state, k) for k in ("cheek", "crown", "body")}
    assert w._v3_hit(QPointF(0, 0))[0] is None
    assert w._hit_zone(QPoint(0, 0)) == "outside"
    for kind in ("cheek", "crown"):
        w._update_hover_cursor(find(w, state, kind))
        assert w.cursor().shape() == Qt_OpenHand()
    w._update_hover_cursor(find(w, state, "body"))
    assert w.cursor().shape() != Qt_OpenHand()


def Qt_OpenHand():
    from PySide6.QtCore import Qt
    return Qt.OpenHandCursor


@pytest.mark.parametrize("state", ["bed", "desk"])
def test_furniture_is_not_a_hit_and_is_outside_the_mask(qapp, scene_window, state):  # noqa: F811
    w, t, spy = scene_window(state)
    points = far_furniture(w, state)
    assert points
    region = w.mask()
    for p in points:
        assert w._v3_hit(QPointF(p))[0] is None
        assert not region.contains(p)                     # 点穿：操作系统把点击交给下面的窗口
        w._update_hover_cursor(p)
        assert w.cursor().shape() != Qt_OpenHand()
    assert spy.clicked == [] and spy.knocked == []


def test_quilt_and_body_count_as_the_character(qapp, scene_window):  # noqa: F811
    w, t, spy = scene_window("bed")
    pos = find(w, "bed", "body")
    assert w.mask().contains(pos)
    click(w, pos)
    assert spy.clicked == [1] and spy.gesture == []


# ---- 拎起 ----
@pytest.mark.parametrize("state", SCENE_STATES)
def test_cheek_lift_cuts_to_standing_at_once_and_the_scene_returns_after_landing(qapp, scene_window, state):  # noqa: F811
    w, t, spy = scene_window(state)
    base = w.normal_width
    start = find(w, state, "cheek")
    g0 = w.mapToGlobal(start)
    feet0 = w.x() + w.width() / 2
    overlay = w._v3_scene_overlay
    rel0 = None if overlay is None else (overlay.x() - feet0, overlay.y() - w.y())
    origin = w.pos()
    press(w, start)
    gmove(w, g0, 0, -8)
    assert not w.lifting and w._v3_scene_w == 1.0            # 没到 12px：还不是拎起
    gmove(w, g0, 0, -20)
    assert w.lifting and w.is_dragging and spy.drags == [1]
    assert w._v3_scene_w == 0.0                                # 不淡化，立刻切回站姿
    assert w._sw == base and w.width() == base + 2 * MARGIN_X
    assert overlay is None or not overlay.isVisible()
    assert "cheek_pull" not in spy.gesture
    assert w.pos().y() == origin.y() - 20
    x_cut = w.x()
    for i in range(1, 7):
        step(w, t)
        gmove(w, g0, 0, -20 - i * 10)
    assert w.x() == x_cut and w.pos().y() == origin.y() - 80  # 窗口跟着鼠标走，没有跳变
    assert w._v3_scene_w == 0.0
    t[0] += 1.0
    w.advance_to(t[0])
    grelease(w, g0, 0, -80)
    assert not w.lifting and not w.is_falling and spy.finished == [1]
    run(w, t, 0.8)
    assert w._v3_scene_w == 1.0                                # 状态没变：落稳后淡回 scene
    assert w.pos().y() < origin.y()                            # 原地停留
    if overlay is not None:                                    # 家具跟到了新位置
        feet = w.x() + w.width() / 2
        assert overlay.isVisible()
        assert abs((overlay.x() - feet) - rel0[0]) <= 1 and abs((overlay.y() - w.y()) - rel0[1]) <= 1


def test_lifting_a_bed_restores_the_standing_width_without_the_window_jumping(qapp, scene_window):  # noqa: F811
    w, t, spy = scene_window("bed")
    assert w._sw > w.normal_width
    start = find(w, "bed", "cheek")
    g0 = w.mapToGlobal(start)
    feet = w.x() + w.width() / 2
    press(w, start)
    gmove(w, g0, 0, -20)
    assert w._sw == w.normal_width
    assert abs((w.x() + w.width() / 2) - feet) <= 1.0           # 脚底中心不动
    grelease(w, g0, 0, -20)


def test_pressing_the_cheek_in_a_scene_uses_the_default_lift_pivot(qapp, scene_window):  # noqa: F811
    w, t, _ = scene_window("desk")
    press(w, find(w, "desk", "cheek"))
    assert w._v3_press_point is None
    release(w, find(w, "desk", "cheek"))


# ---- 捏脸 ----
@pytest.mark.parametrize("state", SCENE_STATES)
def test_pinching_does_nothing_but_hints_when_pulled_far(qapp, scene_window, state):  # noqa: F811
    w, t, spy = scene_window(state)
    start = find(w, state, "cheek")
    g0 = w.mapToGlobal(start)
    origin = w.pos()
    press(w, start)
    gmove(w, g0, 3, 0)
    assert spy.ignored == []                                   # 容差内
    gmove(w, g0, 30, 0)
    assert spy.ignored == [1]
    gmove(w, g0, 60, 5)
    assert spy.ignored == [1]                                  # 只提示一次
    assert "cheek_pull" not in spy.gesture
    assert not w._v3_animator.dragging and not w._v3_animator.reaction.active
    assert not w.is_dragging and not w.lifting and w.pos() == origin
    grelease(w, g0, 60, 5)
    assert spy.clicked == [] and "cheek_release" not in spy.gesture and spy.drags == []


def test_clicking_the_cheek_in_a_scene_is_an_ordinary_poke(qapp, scene_window):  # noqa: F811
    w, t, spy = scene_window("desk")
    click(w, find(w, "desk", "cheek"))
    assert spy.clicked == [1] and spy.gesture == [] and spy.ignored == []


# ---- 摸头 ----
@pytest.mark.parametrize("state", SCENE_STATES)
def test_patting_tilts_the_whole_image_a_little_and_it_comes_back(qapp, scene_window, state):  # noqa: F811
    w, t, spy = scene_window(state)
    start = find(w, state, "crown")
    press(w, start)
    angles = []
    for i in range(1, 25):
        move(w, start + QPoint(20 * (1 if (i // 2) % 2 == 0 else -1) * (i % 2 + 1), 0))
        step(w, t)
        angles.append(w._v3_scene_affine[1])
    assert len(spy.patted) >= 1
    assert max(abs(a) for a in angles) > 0.05                  # 真的在晃
    assert max(abs(a) for a in angles) <= 1.0 + 1e-6           # 最多 ±1°
    release(w, start)
    assert spy.clicked == [] and spy.knocked == [] and spy.drags == []
    run(w, t, 1.5)
    assert abs(w._v3_scene_affine[1]) < 0.05


# ---- 敲头 ----
@pytest.mark.parametrize("state", SCENE_STATES)
def test_knocking_squashes_at_most_two_percent_with_gold_stars(qapp, scene_window, state):  # noqa: F811
    w, t, spy = scene_window(state)
    pos = find(w, state, "crown")
    click(w, pos)
    assert spy.knocked == [False] and spy.clicked == []
    sy, stars = [], 0
    for _ in range(40):
        step(w, t)
        sy.append(w._v3_scene_affine[0])
        stars += w._v3_scene_stars is not None
    assert w._v3_animator.pose.star_effects or stars > 0
    assert stars > 0                                           # 金星画出来过
    assert min(sy) < 0.997 and min(sy) >= 0.98 - 1e-6          # 下压，但不超过 2%
    run(w, t, 1.5)
    assert 0.999 <= w._v3_scene_affine[0] <= 1.0125            # 回弹后只剩呼吸
    assert w._v3_scene_stars is None


def test_the_third_knock_within_the_window_protests(qapp, scene_window):  # noqa: F811
    w, t, spy = scene_window("bed")
    pos = find(w, "bed", "crown")
    for _ in range(3):
        click(w, pos)
        run(w, t, 0.3)
    assert spy.knocked == [False, False, True] and spy.clicked == [] and spy.patted == []


# ---- 挠痒 ----
@pytest.mark.parametrize("state", SCENE_STATES)
def test_rubbing_the_body_never_tickles(qapp, scene_window, state):  # noqa: F811
    w, t, spy = scene_window(state)
    start = find(w, state, "body")
    press(w, start)
    x, sign = 0, 1
    for _ in range(30):
        x += sign * 12
        sign = -sign
        move(w, start + QPoint(x, 0))
        step(w, t, .15)
    release(w, start + QPoint(x, 0))
    assert "tickle" not in spy.gesture and "belly" not in spy.gesture
    assert not w._v3_animator.tickle.active and spy.clicked == []


# ---- 锚点 ----
@pytest.mark.parametrize("height", [160, 260, 320])
@pytest.mark.parametrize("state", SCENE_STATES)
def test_head_and_mouth_anchors_come_from_the_scene_and_stay_in_the_window(qapp, scene_window, state, height):  # noqa: F811
    w, t, _ = scene_window(state, height)
    scene = w._v3_scenes[state]
    head = w.mapFromGlobal(w.head_anchor())
    mouth = w.mapFromGlobal(w.mouth_anchor())
    ex, ey = scene_px(w, scene, *scene.head_top)
    assert abs(head.x() - ex) <= 1 and abs(head.y() - (ey + w._sh * 0.04)) <= 1.5
    mx, my = scene_px(w, scene, *scene.mouth)
    assert abs(mouth.x() - mx) <= 1 and abs(mouth.y() - my) <= 1
    assert 0 <= head.x() <= w.width() and 0 <= head.y() <= w.height()
    assert head.y() < mouth.y()                               # 头顶在嘴上方
    top = min(y for y in range(w.height()) for x in range(0, w.width(), 2)
              if w.mask().contains(QPoint(x, y)))
    assert head.y() <= top + 0.2 * w.height()                 # 离角色最高处不远（不飘在空中）


def test_anchors_switch_back_to_the_standing_ones_and_moved_is_emitted(qapp, scene_window):  # noqa: F811
    w, t, _ = scene_window("desk")
    moved = []
    w.moved.connect(lambda: moved.append(1))
    scene_head = w.head_anchor()
    settle(w, t, "idle", 0.6)
    assert moved                                              # 离开 scene：锚点换了
    assert w.head_anchor() != scene_head
    moved.clear()
    w.set_state("collapse", animate=False)
    run(w, t, 0.6)
    assert moved and w.head_anchor() == w.mapToGlobal(QPoint(*map(round, (
        scene_px(w, w._v3_scenes["collapse"], *w._v3_scenes["collapse"].head_top)[0],
        scene_px(w, w._v3_scenes["collapse"], *w._v3_scenes["collapse"].head_top)[1] + w._sh * 0.04))))


# ---- 睡觉 Z ----
def test_bed_z_starts_from_the_scene_anchor(qapp, scene_window):  # noqa: F811
    from shion.effects import Z_ORIGIN
    w, t, _ = scene_window("bed", 260)
    z = w._sleep_z
    assert z is not None and z.isVisible()
    scene = w._v3_scenes["bed"]
    ex, ey = scene_px(w, scene, *scene.z_anchor)
    start = w.mapToGlobal(QPoint(round(ex), round(ey)))
    assert abs(z.x() + round(Z_ORIGIN[0] * z.scale) - start.x()) <= 2
    assert abs(z.y() + round(Z_ORIGIN[1] * z.scale) - start.y()) <= 2


@pytest.mark.parametrize("state", ["desk", "collapse"])
def test_desk_and_collapse_have_no_z(qapp, scene_window, state):  # noqa: F811
    w, t, _ = scene_window(state)
    assert w._sleep_z is None or not w._sleep_z.isVisible()


def test_standing_sleep_z_is_where_v2_puts_it(qapp, scene_window):  # noqa: F811
    from shion.effects import Z_ORIGIN, sleep_z_anchor
    w, t, _ = scene_window("sleep", scene=False)
    assert w._v3_scene_w == 0.0
    z = w._sleep_z
    assert z is not None and z.isVisible() and w.v3_sleep_z_anchor("sleep") is None
    anchor = sleep_z_anchor(w, "sleep")
    assert (z.x() + round(Z_ORIGIN[0] * z.scale), z.y() + round(Z_ORIGIN[1] * z.scale)) == (anchor.x(), anchor.y())


# ---- 换边冻结 ----
def test_side_switch_is_frozen_while_a_scene_is_shown_and_resumes_after(qapp, scene_window):  # noqa: F811
    import time
    w, t, _ = scene_window("bed", 200, 1.0, auto_side=True, x=100)
    before = w.v3_stats["side_switches"]
    side = w.cheek_side
    run(w, t, 3.0)
    assert w.v3_stats["side_switches"] == before and w._v3_side_target is None and w.cheek_side == side
    w.set_state("idle", animate=False)
    run(w, t, 0.6)
    assert w._v3_scene_w == 0.0
    deadline = time.time() + 60
    while w.v3_stats["side_switches"] == before and time.time() < deadline:
        run(w, t, 0.1)
        time.sleep(.005)
    if desired_other_side(w, side):
        assert w.v3_stats["side_switches"] == before + 1      # 回站姿后按原规则补换


def desired_other_side(w, side):
    from shion.v3_display import desired_side
    screen = w.screen().availableGeometry()
    return desired_side(w.x() + w.width() // 2, screen.x(), screen.width(), side) != side


def test_a_pending_side_preparation_is_cancelled_when_a_scene_starts(qapp, scene_window):  # noqa: F811
    w, t, _ = scene_window("desk", 200, 1.0, auto_side=True, x=100)
    w.set_state("idle", animate=False)
    run(w, t, 1.0)
    w.move(600, 200)                                          # 换到另一半边：要开始准备换边
    run(w, t, 0.7)
    w.set_state("bed", animate=False)
    run(w, t, 1.0)
    assert w._v3_scene_w == 1.0 and w._v3_side_target is None


# ---- 其它 ----
def test_right_click_does_not_interrupt_a_scene_gesture(qapp, scene_window):  # noqa: F811
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    w, t, spy = scene_window("bed")
    start = find(w, "bed", "crown")
    press(w, start)
    assert w._v3_gesture == "crown"
    QTest.mouseClick(w, Qt.RightButton, Qt.NoModifier, find(w, "bed", "body"))
    assert w._v3_gesture == "crown"
    release(w, start)
    assert spy.knocked == [False]


def test_focus_out_during_a_scene_gesture_is_clean(qapp, scene_window):  # noqa: F811
    from PySide6.QtGui import QFocusEvent
    w, t, spy = scene_window("desk")
    start = find(w, "desk", "crown")
    press(w, start)
    move(w, start + QPoint(30, 0))
    w.focusOutEvent(QFocusEvent(QEvent.FocusOut))
    assert w._v3_gesture is None
    release(w, start + QPoint(30, 0))
    assert not w.is_pressed and w._v3_scene_w == 1.0
