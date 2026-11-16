"""S9：V3 窗口里的姿势变体（collapse / bed / desk）：直接切换与进入弹跳、遮罩、家具覆盖窗、窗口加宽、呼吸极值帧。"""
import math

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from scipy import ndimage as nd

from shion import v3_scene as vs
from shion.v3_scene_view import local_origin
from tests.test_v3_display import make, qapp  # noqa: F401  (qapp 是 fixture)
from tests.test_v3_scene import EXTREMES, near_furniture, rest_opaque
from tests.test_v3_state_pose import run

SCENE_STATES = ("collapse", "bed", "desk")


@pytest.fixture(autouse=True)
def no_background_scene_jobs(monkeypatch):
    """不在后台预算三个 scene（每个窗口都算会很慢）：用到哪个，窗口同步载入哪个。"""
    from shion.v3_window import V3PetWindow
    monkeypatch.setattr(V3PetWindow, "_v3_scene_prewarm", lambda self: None)


@pytest.fixture
def windows():
    made = []

    def build(qapp, height=200, dpr=1.0, show=True):  # noqa: F811
        w, t = make(qapp, height, dpr)
        w.move(300, 120)
        if show:
            w.show()
        made.append(w)
        return w, t
    yield build
    for w in made:
        w.close()
        w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def track(w, t, seconds):
    """推进 seconds 秒，逐帧记录 (经过的秒数, scene 权重)。"""
    out = []
    start = t[0]
    end = start + seconds
    while t[0] < end:
        t[0] += w._timer.interval() / 1000
        w.advance_to(t[0])
        out.append((round(t[0] - start, 4), w._v3_scene_w))
    return out


def settle(w, t, state, seconds=0.7):
    w.set_state(state, animate=False)
    run(w, t, seconds)


def scene_px(w, scene, x, y):
    """scene 像素 → 诗音窗口坐标（逻辑像素）。"""
    o = local_origin(w, scene, w._v3_scale, 0.0)
    return o.x() + x * w._v3_scale, o.y() + y * w._v3_scale


# ---- 切换：直接切，不淡化 ----
@pytest.mark.parametrize("state", SCENE_STATES)
def test_scene_switches_without_blending(qapp, windows, state):  # noqa: F811
    w, t = windows(qapp)
    w.set_state("idle", animate=False)
    run(w, t, 0.3)
    assert w._v3_scene_w == 0.0 and w._v3_scene_shown is None
    w.set_state(state, animate=False)
    assert w._v3_scene_w == 1.0 and w._v3_scene_shown is w._v3_scenes[state]   # 第一帧就是 scene
    assert {v for _, v in track(w, t, 0.6)} == {1.0}                    # 两个轮廓从不叠在一起
    w.set_state("idle", animate=False)
    assert w._v3_scene_w == 0.0 and w._v3_scene_shown is None
    assert {v for _, v in track(w, t, 0.6)} == {0.0}


def test_scene_to_scene_switch_never_shows_the_standing_pose(qapp, windows):  # noqa: F811
    w, t = windows(qapp)
    settle(w, t, "bed", 0.8)
    rendered = w.v3_stats["rendered"]
    w.set_state("desk", animate=False)
    seen = [(w._v3_scene_w, w._v3_scene_shown.name)]
    for _ in range(40):
        t[0] += w._timer.interval() / 1000
        w.advance_to(t[0])
        seen.append((w._v3_scene_w, w._v3_scene_shown.name))
    assert set(seen) == {(1.0, "desk")}                                 # bed 直接变 desk，中间没有站姿
    assert w.v3_stats["rendered"] == rendered                           # 站姿图一张都没画


def test_leaving_a_scene_renders_a_fresh_standing_image_in_the_same_frame(qapp, windows):  # noqa: F811
    w, t = windows(qapp)
    settle(w, t, "bed", 0.8)
    w._v3_prewarmer.would_block = lambda *args: True                    # 后台正占着锁：平时会把这一帧推迟
    rendered, deferred = w.v3_stats["rendered"], w.v3_stats["deferred"]
    w.set_state("idle", animate=False)
    assert w._v3_scene_w == 0.0
    assert w.v3_stats["rendered"] == rendered + 1 and w.v3_stats["deferred"] == deferred


def test_entering_a_scene_pops_once(qapp, windows):  # noqa: F811
    w, t = windows(qapp)
    w.set_state("idle", animate=False)
    run(w, t, 0.3)
    w.set_state("bed", animate=False)
    start, sy = t[0], [w._v3_scene_affine[0]]
    times = [start]
    for _ in range(40):
        t[0] += 0.016
        w.advance_to(t[0])
        times.append(t[0])
        sy.append(w._v3_scene_affine[0])
    pop = [v for at, v in zip(times, sy) if at - start < vs.ENTER_POP[0]]
    assert min(pop) < 0.985                                             # 压下去
    late = [v for at, v in zip(times, sy) if at - start > vs.ENTER_POP[0] + 0.05]
    assert min(late) >= 0.999 and max(late) <= 1.0125                   # 之后只剩呼吸


class FakeJob:
    """手动完成的后台任务：不开线程，测试里决定什么时候做好。"""

    def __init__(self, fn, *args):
        self.fn, self.args, self._result, self._done = fn, args, None, False

    def finish(self):
        self._result, self._done = self.fn(*self.args), True

    def done(self):
        return self._done

    def result(self):
        return self._result

    def cancel(self):
        return False

    def cancelled(self):
        return False


def test_a_scene_still_loading_keeps_the_current_picture_and_never_blocks(qapp, windows, monkeypatch):  # noqa: F811
    from shion.v3_window import V3PetWindow
    jobs = {}

    def prewarm(self):
        self._v3_scene_jobs.clear()
        for scene in dict.fromkeys(self._v3_scenes.values()):
            job = FakeJob(vs.load_arrays, scene, self._v3_scale * self._v3_dpr)
            self._v3_scene_jobs[self._v3_scene_key(scene)] = jobs[scene.name] = job

    monkeypatch.setattr(V3PetWindow, "_v3_scene_prewarm", prewarm)
    w, t = windows(qapp)
    w.set_state("idle", animate=False)
    run(w, t, 0.3)
    assert set(jobs) == {"collapse", "bed", "desk"}
    w.set_state("bed", animate=False)
    run(w, t, 0.5)
    assert w._v3_scene_w == 0.0 and w._v3_scene_shown is None           # 还没好：继续站姿
    assert w._v3_scene_load_ms == []                                    # 没有同步载入（界面没等）
    jobs["bed"].finish()
    run(w, t, 0.1)
    assert w._v3_scene_w == 1.0 and w._v3_scene_shown.name == "bed"
    w.set_state("desk", animate=False)
    run(w, t, 0.5)
    assert w._v3_scene_shown.name == "bed" and w._v3_scene_w == 1.0     # desk 没好：继续 bed
    assert w._v3_scene_load_ms == []
    jobs["desk"].finish()
    run(w, t, 0.1)
    assert w._v3_scene_shown.name == "desk"                             # 好了：直接换


def test_standing_pose_is_not_squashed_into_the_old_fallback(qapp, windows):  # noqa: F811
    """有整图姿势时，站姿露面（淡入淡出、被拎起）保持原样，不套“瘫倒”的回退姿态（collapse 回退会下压 4%、低头 30）。"""
    w, t = windows(qapp)
    settle(w, t, "collapse", 1.0)
    assert abs(w._v3_pose.head_y) < 8 and w._v3_pose.body_scale > 0.99


# ---- 遮罩：角色可点、家具点穿 ----
@pytest.mark.parametrize("dpr", [1.0, 1.5])
@pytest.mark.parametrize("height", [160, 320])
@pytest.mark.parametrize("state", ["bed", "desk"])
def test_mask_holds_the_character_but_not_the_furniture(qapp, windows, state, height, dpr):  # noqa: F811
    w, t = windows(qapp, height, dpr)
    settle(w, t, state)
    scene = w._v3_scenes[state]
    a = vs.load_arrays(scene, 0.25)
    char = a["alpha"] >= 250
    furniture = (a["furniture"][..., 3] >= 250) & ~nd.binary_dilation(a["alpha"] > 0, iterations=24)     # 离角色远：160 高时遮罩外扩 4 像素 ≈ 37 rig 像素
    assert char.sum() > 1000 and furniture.sum() > 1000

    def to_scene(mask, n=60):
        ys, xs = np.nonzero(mask)
        pick = np.random.default_rng(1).choice(len(xs), min(n, len(xs)), replace=False)
        return [(xs[i] / a["scale"] - a["pad"], ys[i] / a["scale"] - a["pad"]) for i in pick]

    region = w.mask()
    inside = [region.contains(_pt(*scene_px(w, scene, x, y))) for x, y in to_scene(char)]
    outside = [region.contains(_pt(*scene_px(w, scene, x, y))) for x, y in to_scene(furniture)]
    assert sum(inside) >= 0.95 * len(inside)                           # 角色点得到
    assert sum(outside) == 0                                           # 家具点不到（点穿）


def _pt(x, y):
    from PySide6.QtCore import QPoint
    return QPoint(round(x), round(y))


# ---- 覆盖窗 ----
def test_overlay_exists_only_for_furniture_and_is_click_through(qapp, windows):  # noqa: F811
    w, t = windows(qapp)
    settle(w, t, "collapse")
    assert w._v3_scene_overlay is None or not w._v3_scene_overlay.isVisible()   # collapse 没有家具
    for state in ("bed", "desk"):
        settle(w, t, state)
        overlay = w._v3_scene_overlay
        assert overlay is not None and overlay.isVisible()
        assert overlay.windowFlags() & Qt.WindowTransparentForInput
        assert overlay.windowFlags() & Qt.WindowDoesNotAcceptFocus
        before = overlay.pos() - w.pos()
        w.move(w.x() + 137, w.y() - 21)
        assert overlay.pos() - w.pos() == before                       # 跟着诗音窗口走
    settle(w, t, "idle")
    assert not w._v3_scene_overlay.isVisible()


def test_overlay_and_underlay_sit_on_the_same_pixels(qapp, windows):  # noqa: F811
    """家具覆盖窗里的家具和诗音窗口里垫底的整图在同一位置：家具层的不透明像素在整图里也不透明（±1 像素内）。"""
    w, t = windows(qapp, 260)
    settle(w, t, "desk")
    overlay = w._v3_scene_overlay
    rect = overlay.image_rect().translated(overlay.pos() - w.pos())
    scene = w._v3_scenes["desk"]
    ox, oy = local_origin(w, scene, w._v3_scale, vs.SCENE_PAD).x(), local_origin(w, scene, w._v3_scale, vs.SCENE_PAD).y()
    assert abs(rect.left() - ox) < 1e-6 and abs(rect.top() - oy) < 1e-6
    assert rect.width() == pytest.approx((scene.size[0] + 2 * vs.SCENE_PAD) * w._v3_scale)


# ---- 窗口加宽 ----
@pytest.mark.parametrize("height", [160, 200, 260, 320])
def test_window_widens_only_when_the_pose_is_wider_and_the_feet_stay_put(qapp, windows, height):  # noqa: F811
    w, t = windows(qapp, height)
    w.set_state("idle", animate=False)
    run(w, t, 0.3)
    normal = w.width()
    base = w.normal_width
    feet = w.x() + w.width() / 2
    expect = {s: max(base, math.ceil(2 * vs.extra_half_width(w._v3_scenes[s]) * w._v3_scale))
              for s in SCENE_STATES}
    assert expect["bed"] > base and expect["collapse"] == base and expect["desk"] == base
    for state in SCENE_STATES:
        settle(w, t, state)
        assert w._sw == expect[state] and w.normal_width == base
        assert abs((w.x() + w.width() / 2) - feet) <= 1.0              # 脚底中心不动
        settle(w, t, "idle")
        assert w.width() == normal and w._sw == base


# ---- 关掉 scene：回到站姿回退 ----
@pytest.mark.parametrize("state", SCENE_STATES)
def test_switch_off_keeps_the_standing_fallback(qapp, windows, monkeypatch, state):  # noqa: F811
    monkeypatch.setenv(vs.SCENES_ENV, "0")
    w, t = windows(qapp)
    assert w._v3_scenes is None
    settle(w, t, state, 1.0)
    assert w._v3_scene_w == 0.0 and w._v3_scene_overlay is None
    assert w._sw == w.normal_width
    fallback = {"collapse": 24, "bed": 0, "desk": 14}[state]            # 站姿回退：collapse 低头下压、desk 低头
    assert w._v3_pose.head_y >= fallback - 8


# ---- 站姿图只在需要时画 ----
def test_standing_image_is_not_rendered_while_the_scene_is_fully_shown(qapp, windows):  # noqa: F811
    w, t = windows(qapp)
    settle(w, t, "bed", 1.0)
    rendered = w.v3_stats["rendered"]
    run(w, t, 2.0)
    assert w.v3_stats["rendered"] == rendered                          # 满显示时站姿图一张也不画
    masks = w.v3_stats["masks"]
    run(w, t, 1.0)
    assert w.v3_stats["masks"] - masks <= 12                           # 遮罩最多 10 次/秒
    w.set_state("idle", animate=False)
    run(w, t, 0.8)
    assert w.v3_stats["rendered"] > rendered and w._v3_scene_w == 0.0  # 回站姿后重画


def test_interrupting_drops_the_scene_at_once_and_it_cuts_back(qapp, windows):  # noqa: F811
    w, t = windows(qapp)
    settle(w, t, "bed", 0.8)
    assert w._v3_scene_w == 1.0 and w.width() > w.normal_width + 2 * 64 - 1
    w._v3_lifting = True                                               # 拎起：直接切回站姿
    run(w, t, 0.1)
    assert w._v3_scene_w == 0.0
    assert w._sw == w.normal_width and not w._v3_scene_overlay.isVisible()
    w._v3_lifting = False
    t[0] += 0.016
    w.advance_to(t[0])
    assert w._v3_scene_w == 1.0                                        # 放下后第一帧就切回 scene
    assert w._v3_scene_overlay.isVisible()


# ---- 截图 ----
def test_render_scene_frame_includes_the_furniture(qapp, windows):  # noqa: F811
    w, t = windows(qapp, 260)
    settle(w, t, "desk")
    scene = w._v3_scenes["desk"]
    a = vs.load_arrays(scene, 0.25)
    ys, xs = np.nonzero((a["furniture"][..., 3] >= 250) & ~nd.binary_dilation(a["alpha"] > 0, iterations=12))
    x, y = xs[len(xs) // 2] / a["scale"] - a["pad"], ys[len(ys) // 2] / a["scale"] - a["pad"]
    frame = w.render_scene_frame(1)
    union_left = min(0, w._v3_scene_overlay.x() - w.x())
    union_top = min(0, w._v3_scene_overlay.y() - w.y())
    px, py = scene_px(w, scene, x, y)
    assert frame.width() >= w.width() and frame.height() >= w.height()
    assert frame.pixelColor(round(px - union_left), round(py - union_top)).alpha() > 200
    assert w.render_frame(1).size() == frame.size()                    # scene 显示时 render_frame 也带家具


# ---- 呼吸极值帧：窗口里实际画出来的，角色和家具之间不露缝 ----
def frame_alpha(w, sy, angle):
    """固定 scene 的 (纵向缩放, 倾斜)，重建遮罩，返回按遮罩裁剪后的整幅 alpha 和它的原点。"""
    w._v3_scene_override = (sy, angle)
    w._v3_mask_force = True
    w._refresh(w._clock())
    w._update_mask(w._clock())
    frame = w.render_scene_frame(1, clip=True)
    ptr = frame.constBits()
    arr = np.frombuffer(ptr, np.uint8).reshape(frame.height(), frame.bytesPerLine())
    alpha = arr[:, :frame.width() * 4].reshape(frame.height(), frame.width(), 4)[..., 3].copy()
    overlay = w._v3_scene_overlay
    left = min(0, (overlay.x() - w.x()) if overlay is not None and overlay.isVisible() else 0)
    top = min(0, (overlay.y() - w.y()) if overlay is not None and overlay.isVisible() else 0)
    return alpha, (left, top)


@pytest.mark.parametrize("height", [200, 320])
@pytest.mark.parametrize("state", ["bed", "desk"])
@pytest.mark.parametrize("extreme", list(EXTREMES))
def test_no_seam_in_the_real_window_frame_at_breath_extremes(qapp, windows, state, height, extreme):  # noqa: F811
    w, t = windows(qapp, height)
    settle(w, t, state)
    scene = w._v3_scenes[state]
    rest, (left, top) = frame_alpha(w, 1.0, 0.0)
    shown, _ = frame_alpha(w, *EXTREMES[extreme])
    a = vs.load_arrays(scene, w.v3_texture_scale)
    origin = local_origin(w, scene, w._v3_scale, a["pad"])
    ox, oy = round(origin.x() - left), round(origin.y() - top)
    region = rest_opaque(a) & near_furniture(a)
    region = nd.binary_erosion(region, iterations=3)                    # 避开 1～2 像素的取整误差
    ys, xs = np.nonzero(region)
    assert len(xs) > 1000
    fx, fy = xs + ox, ys + oy
    inside = (fx >= 0) & (fx < shown.shape[1]) & (fy >= 0) & (fy < shown.shape[0])
    assert (rest[fy[inside], fx[inside]] >= 250).mean() > 0.99          # 静止帧里这些像素确实不透明
    seam = shown[fy[inside], fx[inside]] < 250
    assert seam.sum() <= 0.002 * inside.sum(), (state, extreme, int(seam.sum()))


@pytest.mark.parametrize("extreme", list(EXTREMES))
def test_collapse_feet_and_hands_hold_still_in_the_real_window_frame(qapp, windows, extreme):  # noqa: F811
    w, t = windows(qapp, 260)
    settle(w, t, "collapse")
    rest, _ = frame_alpha(w, 1.0, 0.0)
    shown, _ = frame_alpha(w, *EXTREMES[extreme])
    solid = rest >= 250
    rows = np.nonzero(solid.any(axis=1))[0]
    cols = np.nonzero(solid.any(axis=0))[0]
    feet = solid.copy()
    feet[:rows.max() - 10] = False
    hands = np.zeros_like(solid)
    hands[:, cols.min():cols.min() + 12] = True
    hands[:, cols.max() - 11:cols.max() + 1] = True
    hands &= solid
    now = shown >= 200
    need = 0.85 if extreme.startswith("tilt") else 0.98
    assert (now & feet).sum() >= need * feet.sum(), (extreme, "feet")
    assert (now & hands).sum() >= 0.75 * hands.sum(), (extreme, "hands")
    labels, _ = nd.label(now)
    sizes = np.bincount(labels.ravel())[1:]
    assert (sizes >= 0.01 * now.sum()).sum() == 1, (extreme, "pieces")  # 变形后仍是一整块


@pytest.mark.parametrize("state", SCENE_STATES)
def test_knock_leaves_no_still_outline_behind(qapp, windows, state):  # noqa: F811
    """敲头压下去时，窗口里最高的不透明像素跟着往下走：没有不动的角色描线留在头顶（以前垫底是整张图，会留下黑边）。"""
    w, t = windows(qapp, 260)
    settle(w, t, state)
    scene = w._v3_scenes[state]
    rest, _ = frame_alpha(w, 1.0, 0.0)
    pressed, _ = frame_alpha(w, 0.96, 0.0)
    top = lambda alpha: int(np.nonzero((alpha >= 128).any(axis=1))[0].min())
    expected = (1 - 0.96) * (scene.ground_y - scene.char_box[1]) * w._v3_scale
    assert expected > 6
    assert top(pressed) - top(rest) >= 0.8 * expected - 1, (state, top(pressed), top(rest), expected)
    # 头顶那几行：压下去之后在原来的轮廓上方不该还有不透明像素
    band = slice(top(rest), top(rest) + int(0.5 * expected))
    assert (pressed[band] >= 128).sum() <= 0.02 * (rest[band] >= 128).sum() + 8
