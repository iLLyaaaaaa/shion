"""shion/v3_scene.py：坐标、命中分区、淡化、量化键、载入，以及“呼吸极值帧不露缝”的分层模型。"""
import math
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from scipy import ndimage as nd

from shion import v3_scene as vs
from tools import v3_scene as tool

FOOT = (544.1, 1416.0)
POKE_MIN = vs.poke_scale(0.92)       # V2 点击压扁最深（animator.SQUASH["click"]）
EXTREMES = {  # (纵向缩放, 倾斜)：呼吸最小/最大、敲头满压、点击压扁、摸头最大倾斜
    "exhale": (1.0, 0.0),
    "inhale": (1.012, 0.0),
    "knock": (1.0 - vs.KNOCK_SQUASH, 0.0),
    "poke": (POKE_MIN, 0.0),
    "knock+poke": ((1.0 - vs.KNOCK_SQUASH) * POKE_MIN, 0.0),      # 最坏：缩回约 4%
    "tilt+": (1.012, 2.5 * vs.PAT_TILT),
    "tilt-": (1.0 - vs.KNOCK_SQUASH, -2.5 * vs.PAT_TILT),
}
BREATH = ("exhale", "inhale")


def synthetic(**kwargs):
    base = dict(name="t", file="t.png", mask="t_char.png", size=(400, 300), anchor_x=200.0, ground_y=300.0,
                char_box=(100, 50, 300, 300), head_scale=1.0, head_top=(200.0, 60.0), mouth=(200.0, 120.0),
                z_anchor=None, cheek=((150.0, 150.0, 30.0, 20.0),), crown=((200.0, 80.0, 60.0, 30.0),),
                breath_gain=1.0, furniture_pixels=1000)
    base.update(kwargs)
    return vs.Scene(**base)


@pytest.fixture(scope="module")
def scenes():
    loaded = vs.load_metadata(env={})
    assert loaded is not None
    return loaded


# ---- 元数据 ----
def test_load_metadata_states_and_switches(tmp_path):
    loaded = vs.load_metadata(env={})
    assert set(loaded) == {"collapse", "bed", "desk"}
    assert loaded["bed"].z_anchor is not None and loaded["desk"].z_anchor is None
    assert not loaded["collapse"].has_furniture and loaded["bed"].has_furniture and loaded["desk"].has_furniture
    assert vs.load_metadata(env={vs.SCENES_ENV: "0"}) is None            # 环境变量关掉
    assert vs.load_metadata(tmp_path / "missing.json", env={}) is None   # 没有 scenes.json
    assert vs.load_metadata(env={vs.SCENES_ENV: "1"}) is not None
    assert vs.scene_for("bed", loaded).name == "bed" and vs.scene_for("idle", loaded) is None
    assert vs.scene_for("bed", None) is None


def test_constants_agree_with_the_asset_tool():
    assert vs.FURNITURE_GAP == tool.FURNITURE_GAP


# ---- 坐标 ----
def test_coordinates_round_trip_and_ground_lands_on_the_foot_line():
    s = synthetic()
    assert vs.to_scene(s, FOOT, FOOT) == (s.anchor_x, s.ground_y)
    assert vs.to_rig(s, (s.anchor_x, s.ground_y), FOOT) == FOOT
    for p in [(10.0, 20.0), (399.5, 0.25), (200.0, 300.0)]:
        back = vs.to_rig(s, vs.to_scene(s, p, FOOT), FOOT)
        assert back == pytest.approx(p)
    assert vs.extra_half_width(s) == 100 + vs.WINDOW_MARGIN


# ---- 仿射 ----
def test_scene_affine_rest_breath_knock_and_pat():
    s = synthetic()
    assert vs.scene_affine(s, 1.0, 0.0, 0.0) == (1.0, 0.0)
    sy, angle = vs.scene_affine(s, 1.012, 0.0, 0.0)
    assert sy == pytest.approx(1.012) and angle == 0
    sy, _ = vs.scene_affine(s, 1.0, vs.KNOCK_HEAD_Y, 0.0)
    assert sy == pytest.approx(1 - vs.KNOCK_SQUASH)                    # 满压最多 2%
    assert vs.scene_affine(s, 1.0, 999.0, 0.0)[0] == pytest.approx(1 - vs.KNOCK_SQUASH)
    assert vs.scene_affine(s, 1.0, -5.0, 0.0)[0] == 1.0                # 向上不放大
    assert vs.scene_affine(s, 1.0, 0.0, 2.5)[1] == pytest.approx(1.0)  # ±2.5° → ±1°
    assert vs.scene_affine(s, 1.0, 0.0, 0.0, vs.poke_scale(0.92))[0] == pytest.approx(0.98)   # 点击压扁只取 1/4
    assert vs.poke_scale(1.0) == 1.0 and vs.poke_scale(1.024) == pytest.approx(1.006)
    assert vs.scene_affine(synthetic(breath_gain=0.5), 1.012, 0, 0)[0] == pytest.approx(1.006)


def test_affine_keeps_the_ground_pivot_and_inverts():
    s = synthetic()
    m = vs.affine_matrix(s, 1.012, 1.0)
    pivot = m @ np.array([s.anchor_x, s.ground_y, 1.0])
    assert pivot[:2] == pytest.approx([s.anchor_x, s.ground_y])
    assert vs.affine_matrix(s, 1.0, 0.0) == pytest.approx(np.eye(3))
    p = (210.0, 120.0)
    moved = m @ np.array([*p, 1.0])
    assert vs.to_rest(s, moved[:2], 1.012, 1.0) == pytest.approx(p)
    # 纵向放大：支点上方的点往上走
    assert (vs.affine_matrix(s, 1.012, 0.0) @ np.array([200.0, 100.0, 1.0]))[1] < 100


# ---- 命中分区 ----
def test_zone_at_priorities_and_透明():
    s = synthetic()
    alpha = np.zeros((300, 400), np.uint8)
    alpha[60:300, 120:280] = 255
    mask = vs.ArrayMask(alpha)
    assert vs.zone_at(s, 150, 150, mask) == "cheek"
    assert vs.zone_at(s, 200, 80, mask) == "crown"
    assert vs.zone_at(s, 200, 250, mask) == "body"
    assert vs.zone_at(s, 10, 10, mask) is None                         # 透明
    assert vs.zone_at(s, 330, 150, mask) is None                       # 角色以外（家具）
    both = synthetic(cheek=((200.0, 80.0, 30.0, 20.0),))               # 重叠时把手优先
    assert vs.zone_at(both, 200, 80, mask) == "cheek"
    assert vs.zone_at(s, -5, -5, mask) is None and vs.zone_at(s, 500, 500, mask) is None
    low = np.full((300, 400), 40, np.uint8)
    assert vs.zone_at(s, 200, 250, vs.ArrayMask(low)) is None          # alpha 不超过阈值不算


def test_array_mask_scale_and_pad():
    alpha = np.zeros((20, 20), np.uint8)
    alpha[10:12, 10:12] = 255                                          # 数组 (10..12) ↔ scene (10/s - pad)
    m = vs.ArrayMask(alpha, scale=0.5, pad=10)                         # scene x = 数组 x / 0.5 - 10
    assert m.contains(10.5, 10.5) and not m.contains(-5, -5)


# ---- 淡化 ----
def test_fade_reaches_one_in_point_three_seconds_and_reverses_smoothly():
    f = vs.FadeWeight()
    assert f.step(True, 0.0) == 0.0
    values = [f.step(True, t / 100) for t in range(1, 31)]
    assert values[-1] == pytest.approx(1.0) and all(b >= a for a, b in zip(values, values[1:]))
    assert 0.4 < values[14] < 0.6                                       # smoothstep 中点
    f = vs.FadeWeight()
    f.step(True, 0.0)
    up = [f.step(True, t / 100) for t in range(1, 16)]                 # 走到一半
    down = [f.step(False, 0.15 + t / 100) for t in range(1, 6)]        # 中途反向
    assert down[0] < up[-1] and abs(down[0] - up[-1]) < 0.1            # 连续，不跳
    assert all(b <= a for a, b in zip(down, down[1:]))
    assert f.snap(False, 1.0) == 0.0 and f.snap(True) == 1.0


def test_draw_key_quantises_and_stars_disable_it():
    s = synthetic()
    a = vs.scene_draw_key(s, 1.0, 1.0, 0.0, 0.3, False)
    assert a == vs.scene_draw_key(s, 1.0, 1.0 + 1e-6, 0.01, 0.3, False)
    assert a != vs.scene_draw_key(s, 1.0, 1.012, 0.0, 0.3, False)
    assert a != vs.scene_draw_key(s, 0.5, 1.0, 0.0, 0.3, False)
    assert a != vs.scene_draw_key(s, 1.0, 1.0, 1.0, 0.3, False)
    assert vs.scene_draw_key(s, 1.0, 1.0, 0.0, 0.3, True) is None


# ---- 载入 ----
@pytest.mark.parametrize("name", ["collapse", "bed", "desk"])
def test_load_arrays_layers(scenes, name):
    s = scenes[name]
    a = vs.load_arrays(s, 0.2)
    width = round((s.size[0] + 2 * vs.SCENE_PAD) * 0.2)
    height = round((s.size[1] + 2 * vs.SCENE_PAD) * 0.2)
    for key in ("full", "char", "furniture"):
        assert a[key].shape == (height, width, 4) and a[key].dtype == np.uint8, key
        assert (a[key][..., :3] <= a[key][..., 3:4]).all(), key           # 预乘：颜色不超过 alpha
    assert a["alpha"].shape == (height, width) and a["size"] == (width, height)
    assert a["scale"] == pytest.approx(width / (s.size[0] + 2 * vs.SCENE_PAD))
    full, char, furniture = (a[k][..., 3].astype(int) for k in ("full", "char", "furniture"))
    opaque = int((full > 8).sum())
    # 整张图是最完整的一层。各层分别缩放，个别像素会差几级（振铃），所以按比例容忍
    assert (full < char - 8).sum() <= 0.001 * opaque and (full < furniture - 8).sum() <= 0.001 * opaque
    assert full.max() == 255 and char.max() == 255
    # 角色层和家具层在原图分辨率上互不重叠（硬边）；缩放后只在交界一两个像素内有抗锯齿
    both = (char > 8) & (furniture > 8)
    assert both.sum() <= 0.02 * (full > 8).sum()


def test_full_layer_is_the_whole_picture_not_a_cutout(scenes):
    """垫底的是整张场景图：角色所在的像素在 full 里也是不透明的（不是挖掉的）。"""
    for name, s in scenes.items():
        a = vs.load_arrays(s, 0.2)
        char_opaque = a["char"][..., 3] >= 250
        assert char_opaque.sum() > 1000
        assert (a["full"][..., 3][char_opaque] >= 235).all(), name
        # 家具图本身是挖掉了角色的；整图不是
        if s.has_furniture:
            assert (a["furniture"][..., 3][char_opaque] <= 8).all(), name     # 缩放的振铃至多几级


def test_collapse_has_no_furniture_layer(scenes):
    a = vs.load_arrays(scenes["collapse"], 0.2)
    assert (a["furniture"][..., 3] > 8).sum() < 200


def test_split_layers_on_a_small_picture():
    image = np.zeros((40, 80, 4), np.uint8)
    image[..., 3] = 255
    image[..., :3] = (200, 100, 50)
    char = np.zeros((40, 80), bool)
    char[:, 40:] = True
    full, char_layer, furniture = vs.split_layers(image, char)
    assert (full[..., 3] == 255).all()                                   # 垫底是整图
    assert (char_layer[:, 40:, 3] == 255).all() and (char_layer[:, :40, 3] == 0).all()
    gap = vs.FURNITURE_GAP
    assert (furniture[:, :40 - gap, 3] == 255).all() and (furniture[:, 40 - gap:, 3] == 0).all()


# ---- 极值帧：角色层呼吸缩放时，和家具层之间不能露出透明缝 ----
# 分层：full（整张场景图，静止，垫底）→ 角色层（变形）→ 覆盖窗里的家具层。诗音窗口的遮罩 =
# 变形后的角色 ∪ seam（家具 SEAM_BAND 以内的静止非家具像素），再外扩 MASK_GROW。
MASK_GROW = 4          # 同 shion/pet_window.py MASK_GROW（逻辑像素）；这里按数组像素用，够盖住 FURNITURE_GAP


def warp(alpha: np.ndarray, scene, scale, pad, sy, angle) -> np.ndarray:
    """把角色层 alpha 按 scene 仿射变形（PIL 双线性，和 Qt 的变换同一个矩阵）。"""
    to_array = np.array([[scale, 0, pad * scale], [0, scale, pad * scale], [0, 0, 1.0]])
    forward = to_array @ vs.affine_matrix(scene, sy, angle) @ np.linalg.inv(to_array)
    inv = np.linalg.inv(forward)
    image = Image.fromarray(alpha).transform(alpha.shape[::-1], Image.Transform.AFFINE,
                                             (*inv[0], *inv[1]), Image.Resampling.BILINEAR)
    return np.asarray(image)


def visible(a: dict, scene, sy, angle, *, underlay: bool) -> np.ndarray:
    """窗口里看到的不透明度：诗音窗口 = （整图垫底 ∩ 遮罩）再叠变形后的角色；覆盖窗 = 家具层。
    underlay=False 是“挖掉角色的图垫底”的错误做法，用作对照。"""
    moved = warp(a["alpha"], scene, a["scale"], a["pad"], sy, angle)
    region = nd.binary_dilation((a["seam"] > 0) | (moved > 0), iterations=MASK_GROW)
    pet = np.maximum(moved, a["full"][..., 3] * region) if underlay else moved
    return np.maximum(pet, a["furniture"][..., 3])


def near_furniture(a: dict) -> np.ndarray:
    """静止整图里：家具本身，以及离家具 SEAM_BAND 以内的像素（缝只会出在这里）。"""
    furniture = a["furniture"][..., 3] > 8
    if not furniture.any():
        return furniture
    return nd.binary_dilation(furniture, iterations=max(1, math.ceil(vs.SEAM_BAND * a["scale"])))


@pytest.mark.parametrize("name", ["bed", "desk"])
@pytest.mark.parametrize("extreme", list(EXTREMES))
def test_no_seam_opens_between_character_and_furniture_at_any_extreme(scenes, name, extreme):
    """呼吸最小/最大（以及敲头、点击压扁、摸头倾斜的极值）：静止帧里不透明、又贴着家具的像素仍不透明。"""
    s = scenes[name]
    a = vs.load_arrays(s, 0.25)
    sy, angle = EXTREMES[extreme]
    rest = (a["full"][..., 3] >= 250) & near_furniture(a)
    assert rest.sum() > 5000
    shown = visible(a, s, sy, angle, underlay=True)
    assert (shown[rest] >= 250).all(), (name, extreme, int((shown[rest] < 250).sum()))


@pytest.mark.parametrize("name", ["bed", "desk"])
def test_the_underlay_is_the_whole_picture(scenes, name):
    """垫底的是整张场景图（角色所在的像素在 full 里也是不透明的），不是挖掉角色的图。"""
    s = scenes[name]
    a = vs.load_arrays(s, 0.25)
    char = a["alpha"] >= 250
    assert (a["full"][..., 3][char] >= 235).all()
    assert (a["furniture"][..., 3][char] <= 8).all()                   # 对照：家具层是挖掉角色的
    assert (a["seam"] > 0).any() and not ((a["seam"] > 0) & (a["furniture"][..., 3] > 8)).any()   # 遮罩里没有家具


@pytest.mark.parametrize("name", ["bed", "desk"])
def test_without_the_full_underlay_the_extremes_would_show_seams(scenes, name):
    """对照：只画“角色层 + 挖掉角色的家具层”，极值帧里贴着家具的地方会有透明缝——证明上面的测试能抓到。"""
    s = scenes[name]
    a = vs.load_arrays(s, 0.25)
    rest = (a["full"][..., 3] >= 250) & near_furniture(a)
    worst = max(int((visible(a, s, *EXTREMES[e], underlay=False)[rest] < 250).sum()) for e in EXTREMES)
    assert worst > 100


@pytest.mark.parametrize("name", ["bed", "desk"])
def test_character_free_air_does_not_leave_a_still_ghost(scenes, name):
    """离家具远的地方不留静止残影：敲头压下去时，头顶那一层真的缩回去了（压扁看得见）。"""
    s = scenes[name]
    a = vs.load_arrays(s, 0.25)
    far = (a["full"][..., 3] >= 250) & ~near_furniture(a) & (a["alpha"] >= 250)
    shown = visible(a, s, *EXTREMES["knock+poke"], underlay=True)
    assert int((shown[far] < 250).sum()) > 100


def test_the_mask_never_includes_furniture_beyond_the_grow_ring(scenes):
    """遮罩只含角色（含静止的缝带）+ 外扩一圈；家具本体（离角色更远）在遮罩外 = 点得穿。"""
    for name in ("bed", "desk"):
        s = scenes[name]
        a = vs.load_arrays(s, 0.25)
        moved = warp(a["alpha"], s, a["scale"], a["pad"], *EXTREMES["inhale"])
        region = nd.binary_dilation((a["seam"] > 0) | (moved > 0), iterations=MASK_GROW)
        far_furniture = (a["furniture"][..., 3] >= 250) & ~nd.binary_dilation(a["alpha"] > 0, iterations=MASK_GROW + 8)
        assert far_furniture.sum() > 5000
        assert not region[far_furniture].any(), name


def test_collapse_feet_and_hands_do_not_shake_loose():
    """collapse 没有家具：脚底（支点在地面线）在所有极值帧里原地不动，两只手只是随呼吸移动，不会和身体分开。"""
    s = vs.load_metadata(env={})["collapse"]
    a = vs.load_arrays(s, 0.25)
    assert not a["seam"].any() and not (a["furniture"][..., 3] > 200).any()        # 没有家具，也没有缝带
    rest = a["alpha"] >= 250
    rows = np.nonzero(rest.any(axis=1))[0]
    cols = np.nonzero(rest.any(axis=0))[0]
    feet = rest.copy()
    feet[:rows.max() - 20] = False                                      # 脚底 20 行
    hands = np.zeros_like(rest)
    hands[:, cols.min():cols.min() + 25] = True                         # 左右两侧各 25 列（手臂/鞋尖）
    hands[:, cols.max() - 24:cols.max() + 1] = True
    hands &= rest
    assert feet.sum() > 50 and hands.sum() > 50
    for extreme, (sy, angle) in EXTREMES.items():
        moved = warp(a["alpha"], s, a["scale"], a["pad"], sy, angle) >= 200
        # 脚底：呼吸与压扁时 99% 以上原地不动；倾斜 ±1° 时脚会随之转动，放宽到 85%
        need = 0.85 if extreme.startswith("tilt") else 0.99
        assert (moved & feet).sum() >= need * feet.sum(), (extreme, "feet")
        # 手：移动不超过手自身尺寸的一小部分，仍与静止位置大部分重合
        assert (moved & hands).sum() >= 0.8 * hands.sum(), (extreme, "hands")
        # 不透明部分仍是一整块（没有因变形裂成两半）
        labels, count = nd.label(moved)
        big = np.bincount(labels.ravel())[1:]
        assert (big >= 0.01 * moved.sum()).sum() == 1, (extreme, "pieces")


def test_ground_row_does_not_move_when_breathing(scenes):
    """支点在地面线：脚底那一行在呼吸极值里原地不动（变形后的角色层与静止层在底边重合）。"""
    for name, s in scenes.items():
        a = vs.load_arrays(s, 0.25)
        rest = a["alpha"] >= 250
        bottom = np.nonzero(rest.any(axis=1))[0].max()
        for extreme in ("inhale", "knock"):
            moved = warp(a["alpha"], s, a["scale"], a["pad"], *EXTREMES[extreme])
            assert (moved[bottom - 1][rest[bottom - 1]] >= 200).mean() > 0.95, (name, extreme)
