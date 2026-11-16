"""S6：V3 状态姿态（低头、下压、工作点头、哈欠、晕头画圈、咀嚼）与嘴部锚点。"""
import math

import pytest
from PySide6.QtCore import QPoint

from shion.pet_window import PROP_STATES, STATES
from shion.v3_display import (REST_POSE, STATE_POSES, WORKING_NOD_DURATION, WORKING_NOD_INTERVAL,
                              StateMotion, StatePose, state_pose)
from tests.test_v3_display import make, qapp  # noqa: F401  (qapp 是 fixture)


def run(w, t, seconds):
    """推进 seconds 秒，逐帧记录 (时间, pose)。"""
    out = []
    end = t[0] + seconds
    while t[0] < end:
        t[0] += w._timer.interval() / 1000
        w.advance_to(t[0])
        out.append((t[0], w._v3_pose))
    return out


# ---- 纯逻辑 ----
def test_every_state_has_a_pose():
    for state in STATES + list(PROP_STATES):
        assert isinstance(state_pose(state), StatePose)
    with pytest.raises(ValueError):
        state_pose("nope")


def test_low_energy_states_look_down_and_breathe_slower():
    for state in ("neglect1", "slump", "collapse", "desk", "working"):
        assert STATE_POSES[state].head_y > 0
    assert STATE_POSES["collapse"].compress > STATE_POSES["slump"].compress > 0
    assert STATE_POSES["collapse"].head_y > STATE_POSES["slump"].head_y
    for state in ("neglect1", "slump", "collapse", "sleep", "bed", "desk"):
        assert STATE_POSES[state].breath_rate < 1
    assert STATE_POSES["idle"] == REST_POSE


def test_working_nods_every_four_to_six_seconds():
    m = StateMotion(seed=5)
    starts, previous = [], 0.0
    for i in range(int(60 / 0.01)):
        now = i * 0.01
        y = m.sample("working", now).head_y
        if y > 0 and previous == 0:
            starts.append(now)
        previous = y
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    assert len(gaps) >= 8
    assert all(WORKING_NOD_INTERVAL[0] - .02 <= g <= WORKING_NOD_INTERVAL[1] + .02 for g in gaps), gaps


def test_working_nod_starts_and_ends_at_rest():
    m = StateMotion(seed=1)
    m.sample("working", 0.0)
    at = m.next_event
    assert m.sample("working", at).head_y == pytest.approx(0, abs=1e-9)
    assert m.sample("working", at + WORKING_NOD_DURATION / 2).head_y > 9
    assert m.sample("working", at + WORKING_NOD_DURATION + .01).head_y == 0


def test_yawn_stretches_up_then_settles():
    m = StateMotion(seed=2)
    m.sample("yawn", 0.0)
    at = m.next_event
    mid = m.sample("yawn", at + 1.2)
    assert mid.head_y < 0 and mid.compress < 0 and mid.arm > 0
    assert m.sample("yawn", at + 3.0) == REST_POSE


def test_dizzy_circle_eases_in_from_rest():
    m = StateMotion(seed=3)
    assert m.sample("dizzy", 10.0) == REST_POSE
    xs = [m.sample("dizzy", 10.0 + i / 60).head_x for i in range(120)]
    assert max(xs) > 4 and min(xs) < -4
    assert max(abs(b - a) for a, b in zip(xs, xs[1:])) < 1.0


def test_chewing_only_while_eating():
    m = StateMotion(seed=4)
    m.chew(0.0, 2.0)
    ys = [m.sample("happy", i / 60).head_y for i in range(120)]
    assert max(ys) > 2.5
    assert m.sample("happy", 2.01) == REST_POSE
    assert m.busy("happy", 1.0) and not m.busy("happy", 2.01)


def test_apply_keeps_the_head_on_the_neck_when_compressed():
    from v3proto.animation import Pose
    out = StatePose(compress=.02, head_y=5).apply(Pose())
    assert out.body_scale == pytest.approx(.98)
    assert out.head_y == pytest.approx(5 + .02 * (1063.4 - 664.0))


# ---- 窗口 ----
def test_state_change_eases_without_jumps(qapp):
    w, t = make(qapp, 200, 1.5)
    w.set_state("idle", animate=False)
    run(w, t, .5)
    # collapse 现在用整图姿势（S9），不再套站姿回退；这里用仍是站姿的 slump 测缓动
    w.set_state("slump", animate=False)
    frames = run(w, t, 1.0)
    ys = [p.head_y for _, p in frames]
    assert max(abs(b - a) for a, b in zip(ys, ys[1:])) < 12
    assert w._v3_pose_static == STATE_POSES["slump"]  # 1 秒内到位
    w.set_state("idle", animate=False)
    ys = [p.head_y for _, p in run(w, t, 1.0)]
    assert max(abs(b - a) for a, b in zip(ys, ys[1:])) < 12
    w.close()


def test_working_nods_on_the_affine_path_without_v2_whole_image_nod(qapp):
    w, t = make(qapp, 200, 1.5)
    w.set_state("working", animate=False)
    w._v3_motion = StateMotion(seed=1)
    w._v3_sway.start = w._v3_sway.end = 1e9  # 排除随机的头发轻摆：只看点头本身
    before = w.v3_stats
    frames = run(w, t, 12)
    after = w.v3_stats
    ys = [p.head_y for _, p in frames]
    assert max(ys) - min(ys) > 8           # 点过头
    assert after["mesh"] - before["mesh"] == 0
    assert w._animator.whole_nod is False
    assert w._animator._nod_sample(t[0]) == 0  # V2 不再整图点头
    w.close()


def test_breath_and_blink_slow_down_in_low_energy_states(qapp):
    w, t = make(qapp, 200, 1.5)
    w.set_state("collapse", animate=False)
    run(w, t, .2)
    assert w._v3_settings.breath_rate == STATE_POSES["collapse"].breath_rate
    assert w._v3_settings.blink_gap == STATE_POSES["collapse"].blink_gap
    w.set_state("idle", animate=False)
    run(w, t, .2)
    assert w._v3_settings.breath_rate == 1 and w._v3_settings.blink_gap == 1
    w.close()


def test_interaction_fades_the_state_pose_out_and_back(qapp):
    w, t = make(qapp, 200, 1.5)
    w.set_state("collapse", animate=False)
    run(w, t, 1.0)
    w._v3_animator.tickle_belly(now=w._v3_animator.clock)
    run(w, t, .6)
    assert w._v3_pose_weight < .1
    w._v3_animator.release_tickle(now=w._v3_animator.clock)
    run(w, t, 3.0)
    assert w._v3_pose_weight == 1
    w.close()


def test_mouth_anchor_sits_on_the_face_and_follows_the_head(qapp):
    w, t = make(qapp, 200, 1.5)
    w.set_state("idle", animate=False)
    run(w, t, .3)
    x, y, bw, bh = w.body_rect()
    m = w.mouth_anchor()
    assert abs(m.x() - (x + bw / 2)) < bw * .1
    assert y + bh * .3 < m.y() < y + bh * .55
    w.set_state("slump", animate=False)   # collapse 是整图姿势（S9），嘴部锚点见 test_v3_scene_window
    run(w, t, 1.0)
    assert w.mouth_anchor().y() > m.y()  # 低头后嘴更低
    w.close()


def test_v2_mouth_anchor_unchanged(qapp):
    from shion.effects import MOUTH_FRACTION
    from shion.pet_window import PetWindow
    w = PetWindow(autostart=False, debug=False)
    x, y, bw, bh = w.body_rect()
    assert w.mouth_anchor() == QPoint(x + bw // 2, y + round(bh * MOUTH_FRACTION))
    w.start_chewing(2.0)  # V2 什么也不做
    w.close()


def test_chewing_nods_the_head(qapp):
    w, t = make(qapp, 200, 1.5)
    w.set_state("happy", animate=False)
    run(w, t, .5)
    w.start_chewing(1.0)
    ys = [p.head_y for _, p in run(w, t, .9)]
    assert max(ys) - min(ys) > 2
    w.close()


def test_default_prototype_settings_keep_old_timing():
    """breath_rate / blink_gap 默认 1：原型的呼吸与眨眼时间线逐位不变。"""
    from v3proto.animation import Animator, Settings
    a = Animator(Settings(expression="neutral"), seed=7)
    poses = [a.advance(1 / 60) for _ in range(600)]
    assert a.breath_time == a.time
    assert math.isfinite(poses[-1].body_scale)


# ---- 给 GPT 的参考图工具 ----
def test_art_refs_match_refs_json(tmp_path):
    from PIL import Image
    from tools.v3_art_refs import build
    meta = build(tmp_path)
    assert meta["canvas"] == [1086, 1448]
    for name, info in meta["images"].items():
        with Image.open(tmp_path / name) as im:
            assert list(im.size) == info["size"], name
            assert im.mode == "RGB"
        x0, y0, x1, y1 = info["rig_box"]
        assert info["size"] == [(x1 - x0) * info["zoom"], (y1 - y0) * info["zoom"]], name


def test_pad_fits_and_centres_on_white(tmp_path):
    from PIL import Image
    from tools.v3_art_refs import pad
    src = tmp_path / "gpt.png"
    Image.new("RGB", (1024, 1536), (255, 0, 0)).save(src)
    out = pad(src, tmp_path / "out.png")
    assert out.size == (1086, 1448)
    assert out.getpixel((543, 724)) == (255, 0, 0)
    assert out.getpixel((2, 724)) == (255, 255, 255)  # 左右白边


# ---- S0 部件拼的表情（tools/v3_s0_faces.py）----
def test_slump_neglect1_and_yawn_use_the_s0_faces():
    from shion.v3_display import STATE_EXPRESSIONS
    from v3proto.render import Rig
    assert STATE_EXPRESSIONS["slump"] == "tired"
    assert STATE_EXPRESSIONS["neglect1"] == "bored"
    assert STATE_EXPRESSIONS["yawn"] == "yawn"
    rig = Rig()
    for face in ("tired", "bored", "yawn"):
        assert face in rig.faces and face in rig.cheek_images
        names = rig.face_parts(face)
        assert sorted(rig.parts[n]["role"] for n in names) == ["eye_l", "eye_r", "mouth"]
        for n in names:
            p = rig.parts[n]
            if p["role"].startswith("eye"):
                px, py = p["blink_pivot"]
                assert p["x"] <= px <= p["x"] + p["size"][0]
                assert p["y"] < py <= p["y"] + p["size"][1]
