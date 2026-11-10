"""S1: --renderer v3 entry, state → V3 expression mapping and texture scale."""
import numpy as np
import pytest
from PySide6.QtCore import Qt

from shion.pet_window import MARGIN_BOTTOM, PROP_STATES, SEQUENCE_GROUPS, STATES, PetWindow
from shion.v3_display import (STATE_EXPRESSIONS, V2_VISIBLE_RATIO, expression_for,
                              logical_scale, texture_scale)

V3_FACES = {"smug", "neutral", "happy", "surprised", "teary", "angry", "sleep", "dizzy"}


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def make(qapp, height=200, dpr=1.0, clock=None):
    from shion.v3_window import V3PetWindow
    t = clock if clock is not None else [100.0]
    w = V3PetWindow(height=height, clock=lambda: t[0], autostart=False, debug=False, pixel_ratio=dpr)
    w.setAttribute(Qt.WA_DontShowOnScreen)
    w.auto_side = False  # 换边另有测试（test_v3_side.py）；其余测试固定左侧
    return w, t


def test_every_state_and_sequence_frame_has_a_v3_expression():
    for state in STATES + list(PROP_STATES):
        base = state if state != "blink" else "idle"
        assert expression_for(state, base) in V3_FACES
    for group in SEQUENCE_GROUPS:
        for i in (1, 2, 3):
            assert expression_for(f"{group}_{i}", "idle") in V3_FACES
    with pytest.raises(ValueError):
        expression_for("no_such_frame", "idle")


def test_blink_and_jump_keep_the_base_expression():
    for base in ("idle", "happy", "neglect2", "sleep"):
        assert expression_for("blink", base) == STATE_EXPRESSIONS[base]
        assert expression_for("jump_2", base) == STATE_EXPRESSIONS[base]


def test_texture_follows_display_height_times_dpr():
    for height in (160, 200, 260, 320):
        assert texture_scale(height, 1.5, 1403) == pytest.approx(1.5 * texture_scale(height, 1, 1403))
        assert logical_scale(height, 1403) * 1403 == pytest.approx(height * V2_VISIBLE_RATIO)


@pytest.mark.parametrize("height", (160, 200, 260, 320))
def test_v3_visible_height_matches_v2(qapp, height):
    from v3proto.render import to_pil
    v3, t = make(qapp, height)
    s = v3._v3_settings
    s.breath = s.blink = s.sway = False  # measure the rest pose, not breathing or hair sway
    t[0] += .3
    v3.advance_to(t[0])
    alpha = np.asarray(to_pil(v3.render_frame(1)))[..., 3]
    v2 = PetWindow(height=height, clock=lambda: t[0], autostart=False, debug=False, pixel_ratio=1.0)
    v2.set_state("idle", animate=False)

    def extent(window):
        # Downscaling leaves a faint halo; compare the silhouettes as seen.
        a = np.asarray(to_pil(window.render_frame(1)))[..., 3]
        ys = np.nonzero((a > 32).any(1))[0]
        return ys.min(), ys.max()

    top3, bottom3 = extent(v3)
    top2, bottom2 = extent(v2)
    assert v3.height() == v2.height()  # same window height, same floor line
    assert abs(bottom3 - bottom2) <= 2
    assert abs((bottom3 - top3) - (bottom2 - top2)) <= max(2, height * .01)
    v2.close(); v3.close()


def test_dpr_changes_texture_not_logical_size(qapp):
    a, _ = make(qapp, 200, 1.0)
    b, _ = make(qapp, 200, 1.5)
    assert a.size() == b.size()
    assert b.v3_texture_scale == pytest.approx(1.5 * a.v3_texture_scale)
    assert b._v3_image.width() == pytest.approx(1.5 * a._v3_image.width(), abs=2)
    a.close(); b.close()


def test_set_height_keeps_feet_and_set_state_changes_expression(qapp):
    w, t = make(qapp, 200)
    w.move(400, 300)
    feet = (w.x() + w.width() / 2, w.y() + w.height() - MARGIN_BOTTOM)
    w.set_height(320)
    assert (w.x() + w.width() / 2, w.y() + w.height() - MARGIN_BOTTOM) == pytest.approx(feet, abs=1)
    assert w.v3_expression == "neutral"
    w.set_state("neglect2", animate=False)
    t[0] += .2
    w.advance_to(t[0])
    assert w.v3_expression == "teary"
    w.close()


def test_snapshot_entry_selects_the_renderer(qapp, tmp_path):
    from shion.app import SnapshotScene, snapshot, window_class
    from shion.v3_window import V3PetWindow
    assert window_class() is PetWindow and window_class("v2") is PetWindow
    assert window_class("v3") is V3PetWindow
    with SnapshotScene("idle", 200) as scene:
        assert type(scene.win) is PetWindow
    out = tmp_path / "v3.png"
    assert snapshot(str(out), "happy", renderer="v3") == 0
    from PIL import Image
    with Image.open(out) as im:
        assert np.asarray(im.convert("RGBA"))[..., 3].any()


# ---- S2: pacing, skipping, mask, DPR, anchor ----
from shion.v3_display import (CALM_MS, FAST_MS, SLEEP_MS, frame_interval,  # noqa: E402
                              hair_moving)


def run_for(w, t, seconds):
    end = t[0] + seconds
    while t[0] < end:
        t[0] += w._timer.interval() / 1000
        w.advance_to(t[0])


def test_frame_interval_tiers_and_hair_speed():
    from shion.v3_display import STILL_MS, WORKING_STILL_MS
    assert frame_interval(True, "idle") == FAST_MS
    assert frame_interval(True, "idle", still=True) == FAST_MS
    # 头发在摆（网格路径）：30 FPS
    assert frame_interval(False, "idle") == CALM_MS == frame_interval(False, "working")
    # 头发静止（仿射路径）：待机 15、工作 20；眨眼/轻摆前临时 30
    assert frame_interval(False, "idle", still=True) == STILL_MS == 66
    assert frame_interval(False, "working", still=True) == WORKING_STILL_MS == 50
    assert frame_interval(False, "idle", still=True, soon=True) == CALM_MS
    for state in ("sleep", "bed", "desk", "collapse"):
        assert frame_interval(False, state) == SLEEP_MS
        assert frame_interval(False, state, still=True) == SLEEP_MS
    assert not hair_moving({"bangs": 1.0}, {"bangs": 1.05}, 1 / 30)   # gentle idle sway
    assert hair_moving({"bangs": 1.0}, {"bangs": 2.0}, 1 / 60)        # flicked


@pytest.mark.parametrize("state,interval", (("idle", 66), ("working", 50), ("sleep", SLEEP_MS)))
def test_calm_states_drop_frame_rate(qapp, state, interval):
    w, t = make(qapp, 200, 1.5)
    w.set_state(state, animate=False)
    run_for(w, t, 1.0)
    before = w.v3_stats
    intervals = []
    end = t[0] + 3.0
    while t[0] < end:  # 第一次轻摆在创建后 6 秒以后，这 4 秒头发静止
        t[0] += w._timer.interval() / 1000
        w.advance_to(t[0])
        intervals.append(w._timer.interval())
    after = w.v3_stats
    assert set(intervals) <= {interval, CALM_MS}  # 只有眨眼前后临时 30 FPS
    assert intervals.count(interval) > len(intervals) / 2
    assert (after["rendered"] - before["rendered"]) / 3.0 <= 1000 / interval + 8
    assert after["mesh"] == before["mesh"]
    w.close()


def test_unchanged_frame_is_not_rendered_again(qapp):
    w, t = make(qapp, 200)
    s = w._v3_settings
    s.breath = s.blink = s.sway = False
    w._animator.calm = True  # no V2 idle rocking either
    run_for(w, t, .5)
    before = w.v3_stats
    calls = []
    w.update = lambda *a: calls.append(1)
    run_for(w, t, 1.0)
    after = w.v3_stats
    assert after["refresh"] > before["refresh"]
    rendered = after["rendered"] - before["rendered"]
    assert rendered <= 2 and len(calls) <= 2
    w.close()


def test_interaction_uses_sixty_fps(qapp):
    w, t = make(qapp, 200)
    w._v3_settings.pinch = True
    w._v3_animator.press((325., 610.))
    w._v3_animator.drag((260., 610.))
    t[0] += 1 / 60
    w.advance_to(t[0])
    assert w._timer.interval() == FAST_MS
    w.close()


def test_mask_rate_limited_and_follows_state(qapp):
    w, t = make(qapp, 200)
    run_for(w, t, .5)
    before = w.v3_stats["masks"]
    run_for(w, t, 2.0)
    assert (w.v3_stats["masks"] - before) / 2.0 <= 10.5
    before = w.v3_stats["masks"]
    w.set_state("stop", animate=False)
    t[0] += .001
    w.advance_to(t[0])
    assert w.v3_stats["masks"] > before  # state change updates at once
    region = w._v3_region
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QImage, QPainter
    img = QImage(w.size(), QImage.Format_ARGB32)
    img.fill(0)
    painter = QPainter(img)
    w._draw_sprite(painter, w._frame)  # 与遮罩同一窗口坐标系
    painter.end()
    alpha = np.array([[img.pixelColor(x, y).alpha() for x in range(img.width())]
                      for y in range(0, img.height(), 4)])
    rows, xs = np.nonzero(alpha > 0)
    y, x = int(rows[len(rows) // 2]) * 4, int(xs[np.argmax(rows == rows[len(rows) // 2])])
    assert region.contains(QPoint(x, y))
    assert region.contains(QPoint(x - 3, y))  # 外扩 4px
    w.close()


def test_dpr_change_rebuilds_once_and_keeps_feet(qapp):
    from shion.v3_window import V3PetWindow
    t = [100.0]
    w = V3PetWindow(height=200, clock=lambda: t[0], autostart=False, debug=False)
    w.setAttribute(Qt.WA_DontShowOnScreen)
    w.move(300, 300)
    feet = (w.x() + w.width() / 2, w.y() + w.height() - MARGIN_BOTTOM)
    first = w._v3_dpr
    other = 1.0 if first != 1.0 else 1.5
    w.set_device_pixel_ratio(other)
    a = w._v3_renderer
    assert w._v3_dpr == other and w._v3_image.devicePixelRatio() == other
    w.set_device_pixel_ratio(first)
    w.set_device_pixel_ratio(other)
    assert w._v3_renderer is a  # cached, not rebuilt
    assert (w.x() + w.width() / 2, w.y() + w.height() - MARGIN_BOTTOM) == pytest.approx(feet, abs=1)
    w.close()


def test_head_anchor_is_near_the_top_of_the_head(qapp):
    from v3proto.render import to_pil
    w, t = make(qapp, 260)
    alpha = np.asarray(to_pil(w.render_frame(1)))[..., 3]
    top = np.nonzero((alpha > 32).any(1))[0].min()
    anchor = w.mapFromGlobal(w.head_anchor())
    assert 0 <= anchor.y() - top <= 260 * .08
    assert abs(anchor.x() - w.width() / 2) <= 1
    w.close()


def test_panel_snapshot_with_v3_pet(qapp):
    from shion.app import render_snapshot_panel
    img = render_snapshot_panel("permission", with_pet=True, renderer="v3")
    assert not img.isNull() and img.width() > 0


# ---- S2 优化：眨眼量化、后台预热、整数描边 ----
from concurrent.futures import Future  # noqa: E402

from shion.v3_prewarm import BLINK_LEVELS, quantize_eye  # noqa: E402


class SyncExecutor:
    def __init__(self):
        self.calls = 0

    def submit(self, fn, *args):
        self.calls += 1
        f = Future()
        f.set_result(fn(*args))
        return f


@pytest.fixture
def sync_prewarm(monkeypatch):
    import shion.v3_window as vw
    executor = SyncExecutor()
    monkeypatch.setattr(vw, "PREWARM_EXECUTOR", executor)
    return executor


def test_eye_levels_are_twentieths():
    assert len(BLINK_LEVELS) == 19 and BLINK_LEVELS[0] == 0.1 and BLINK_LEVELS[-1] == 1.0
    for v in np.linspace(0.1, 1.0, 400):
        q = quantize_eye(float(v))
        assert abs(q * 20 - round(q * 20)) < 1e-9 and abs(q - v) <= 0.025 + 1e-9
    assert quantize_eye(1.0) == 1.0 and quantize_eye(0.99) == 1.0


def _blink_frames(w, t, seconds):
    import shion.v3_window as vw
    seen = []
    original = w._v3_renderer.render
    original_affine = vw.render_affine

    def render(settings, pose, **kw):
        seen.append(pose.eye_scale)
        return original(settings, pose, **kw)

    def affine(renderer, settings, pose):  # 头发静止时走仿射路径
        seen.append(pose.eye_scale)
        return original_affine(renderer, settings, pose)
    w._v3_renderer.render = render
    vw.render_affine = affine
    try:
        for _ in range(int(seconds * 60)):
            t[0] += 1 / 60
            w.advance_to(t[0])
    finally:
        w._v3_renderer.render = original
        vw.render_affine = original_affine
    return seen


def test_renderer_only_sees_quantized_eyes_and_second_blink_composes_nothing(qapp, sync_prewarm):
    w, t = make(qapp, 200)
    w.set_state("idle", animate=False)
    first = _blink_frames(w, t, 7.0)  # 眨眼间隔 3～6 秒
    assert any(v < 1 for v in first)
    assert all(v in BLINK_LEVELS for v in first)
    surface = w._v3_renderer.head_surface
    calls = []
    original = surface._compose_image
    surface._compose_image = lambda *a, **k: calls.append(1) or original(*a, **k)
    second = _blink_frames(w, t, 7.0)
    assert any(v < 1 for v in second)
    assert calls == []
    w.close()


def test_prewarm_fills_open_faces_then_current_blinks(qapp, sync_prewarm):
    w, t = make(qapp, 200)
    frames = w._v3_renderer.head_surface.frames
    for expression in set(STATE_EXPRESSIONS.values()):
        assert (expression, 1.0) in frames
    w.set_state("happy", animate=False)
    t[0] += .01
    w.advance_to(t[0])
    assert all(("happy", level) in frames for level in BLINK_LEVELS)
    w.close()


def test_prewarm_prepares_cheek_assets_for_every_state_expression(qapp, sync_prewarm):
    w, t = make(qapp, 200)
    cheek = w._v3_renderer.head_surface.cheek
    for expression in set(STATE_EXPRESSIONS.values()):
        assert expression in cheek.backgrounds and expression in cheek.protection
    w.close()


def test_prewarm_builds_reaction_face_patches_so_first_pinch_does_not_stall(qapp, sync_prewarm):
    w, t = make(qapp, 200)
    cache = w._v3_renderer.head_surface.reaction_face.cache
    for expression in set(STATE_EXPRESSIONS.values()):
        assert (expression, 1.0, True) in cache
    for face in w._v3_rig.faces:
        assert (face, 1.0, False) in cache
    w.close()


def test_evicted_renderer_prewarm_is_closed(qapp, sync_prewarm):
    w, t = make(qapp, 200)
    first = w._v3_prewarmer
    w.set_height(260)
    w.set_height(320)  # 渲染器缓存 2 份，200 那份被挤掉
    assert first.closed and first._build(w._v3_settings, 1.0) is None
    assert not w._v3_prewarmer.closed
    w.close()


def test_affine_ok_classifies_poses():
    from dataclasses import replace
    from v3proto.animation import Pose
    from shion.v3_layers import affine_ok
    base = Pose(body_scale=.996, head_y=1.4, eye_scale=.35)  # 呼吸 + 眨眼
    assert affine_ok(base)
    assert affine_ok(replace(base, angles={"bangs": .04, "ahoge": -.04}))
    assert affine_ok(replace(base, head_roll=2., head_x=3., body_roll=1.5, arm_degrees=4.,
                             leg_degrees=3., root_offset=(5., -8.), root_roll=2.))
    assert not affine_ok(replace(base, angles={"bangs": .06}))
    assert not affine_ok(replace(base, pinch_delta=(-3., 0.)))
    assert not affine_ok(replace(base, reaction_face="angry"))
    assert not affine_ok(replace(base, star_effects=((.1, ()),)))


def _diff(a, b):
    from shion.v3_window import _premultiplied
    x, y = _premultiplied(a).astype(int), _premultiplied(b).astype(int)
    assert x.shape == y.shape
    d = np.abs(x - y)
    return float(d.mean()), int(d.max())


@pytest.mark.parametrize("fields", (
    dict(body_scale=.996, head_y=1.37),
    dict(body_scale=.998, head_y=.61, eye_scale=.4),
    dict(head_roll=1.7, head_x=1.2, head_y=.8),
    dict(head_roll=-2.3, body_roll=1.1, root_offset=(4., -6.), root_roll=1.5),
))
def test_affine_path_matches_mesh_path(qapp, fields):
    from v3proto.animation import Pose
    from shion.v3_layers import render_affine
    w, t = make(qapp, 320, 1.5)
    r, s = w._v3_renderer, w._v3_settings
    pose = Pose(**fields)
    affine = render_affine(r, s, pose)
    # 头不转时给 1e-9° 让原型强制进网格（等于恒等网格）
    forced = pose if pose.head_roll else Pose(**{**fields, "head_roll": 1e-9})
    mean, peak = _diff(affine, r.render(s, forced))
    assert mean < .5 and peak <= 8, (mean, peak)
    w.close()


def test_sway_envelope_is_smooth_and_intermittent():
    from shion.v3_layers import EPISODE, FADE, SwayEnvelope
    e = SwayEnvelope(0., seed=3)
    start = e.start
    assert 6 <= start <= 12
    values = [e.value(i / 120) for i in range(int((start + EPISODE + 1) * 120))]
    assert max(abs(b - a) for a, b in zip(values, values[1:])) < 1.6 / (120 * FADE)
    assert values[int((start - .1) * 120)] == 0 and values[int((start + EPISODE / 2) * 120)] == 1
    assert values[-1] == 0 and e.start >= start + EPISODE + 6
    # 互动：立刻满幅，停止后 2×FADE 内回到 0
    e.force(100.)
    assert e.value(100.) == 1
    assert e.value(100. + 2 * FADE) == 0


@pytest.mark.parametrize("seed", (1, 2, 3))
def test_idle_is_mostly_affine_and_hair_settles_after_each_episode(qapp, seed):
    from shion.v3_layers import SwayEnvelope
    w, t = make(qapp, 200, 1.5)
    w.set_state("idle", animate=False)
    # 轻摆间隔是随机的；不固定种子时 30 秒里可能摆 2 次也可能摆 3 次，占比会在
    # 60% 上下浮动。固定种子让结果可重复（时钟本来就是假的）。
    w._v3_sway = SwayEnvelope(t[0], seed=seed)
    affine = mesh = 0
    angles, last_sway = [], -1e9
    end = t[0] + 30
    while t[0] < end:
        t[0] += w._timer.interval() / 1000
        before = w.v3_stats
        w.advance_to(t[0])
        after = w.v3_stats
        affine += after["affine"] - before["affine"]
        mesh += after["mesh"] - before["mesh"]
        if w._v3_settings.sway_degrees > 0:
            last_sway = t[0]
        angle = max(map(abs, w._v3_angles.values()), default=0.)
        angles.append(angle)
        if t[0] - last_sway >= 1.0:  # 包络回到 0 已满 1 秒：头发必须静止
            assert angle < .05, (t[0], angle)
    assert mesh > 0                     # 30 秒里至少摆过一次
    assert affine / (affine + mesh) >= .6
    # 相邻帧角度变化有限：不跳变
    assert max(abs(b - a) for a, b in zip(angles, angles[1:])) < 1.5
    w.close()
