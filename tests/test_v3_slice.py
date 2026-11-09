"""tools/v3_slice.py 的测试：合成线稿图，不依赖 raw 素材。"""
import numpy as np
from PIL import Image, ImageDraw

from tools import v3_slice as vs

BROWN = (70, 30, 25)
NAVY = (50, 50, 80)


def _scene():
    """白底上两个带深棕轮廓的形状：左边的圆（下层），右边压上去的方块（上层）。"""
    im = Image.new("RGB", (200, 140), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.ellipse([20, 20, 120, 120], fill=(250, 220, 210), outline=BROWN, width=5)
    d.rectangle([90, 40, 170, 110], fill=(240, 150, 60), outline=BROWN, width=5)
    return np.asarray(im)


def test_line_mask_brown_and_black_but_not_navy():
    rgb = np.full((20, 60, 3), 255, np.uint8)
    rgb[:, 0:10] = BROWN
    rgb[:, 20:30] = (5, 0, 0)       # 接近纯黑的轮廓
    rgb[:, 40:50] = NAVY            # 制服深蓝
    fg = np.ones(rgb.shape[:2], bool)
    m = vs.line_mask(rgb, fg)
    assert m[10, 5] and m[10, 25]
    assert not m[10, 45]


def test_enclosed_regions_and_holes():
    rgb = _scene()
    fg = np.asarray(Image.fromarray(rgb).convert("L")) < 250
    fg = vs.nd.binary_fill_holes(fg)
    line = vs.line_mask(rgb, fg)
    lab, line2 = vs.enclosed_regions(fg, line)
    # 圆露出来的部分、方块各是一块
    assert lab[70, 50] > 0 and lab[75, 130] > 0 and lab[70, 50] != lab[75, 130]


def test_watershed_splits_along_line_with_seeds():
    rgb = _scene()
    fg = vs.nd.binary_fill_holes(np.asarray(Image.fromarray(rgb).convert("L")) < 250)
    line = vs.line_mask(rgb, fg)
    markers = np.zeros(fg.shape, np.int32)
    i_low, i_up = vs.SLICE_PARTS.index("head_skin") + 1, vs.SLICE_PARTS.index("bangs") + 1
    markers[65:75, 40:50] = i_low
    markers[70:80, 130:140] = i_up
    markers[~fg] = -1
    seg = vs.segment(rgb, fg, line, markers)
    seg, fg2 = vs.fill_unassigned(seg, fg, rgb)
    assert seg[70, 50] == i_low and seg[75, 130] == i_up
    assert (seg[fg2] > 0).all()


def test_fill_unassigned_turns_inner_white_hole_into_background():
    rgb = np.full((80, 80, 3), 255, np.uint8)
    fg = np.ones((80, 80), bool)
    seg = np.zeros((80, 80), np.int32)
    seg[:, :20] = 1
    seg[:, 60:] = 2
    rgb[:, :20] = (200, 100, 100)
    rgb[:, 60:] = (100, 100, 200)
    seg2, fg2 = vs.fill_unassigned(seg, fg, rgb)
    assert not fg2[40, 40]                # 中间 40x80 的纯白 → 背景
    assert fg2[40, 10] and seg2[40, 10] == 1


def test_regions_overrides_by_point_and_part_image():
    enclosed = np.zeros((60, 120), np.int32)
    enclosed[5:55, 5:55] = 1
    enclosed[5:55, 65:115] = 2
    seg = np.zeros_like(enclosed)
    seg[enclosed == 1] = vs.SLICE_PARTS.index("body") + 1
    seg[enclosed == 2] = vs.SLICE_PARTS.index("arm_l") + 1
    regions, rlab = vs.split_regions(enclosed, seg)
    assert [r["id"] for r in regions] == ["R001", "R002"]
    assert regions[0]["part"] == "body" and regions[1]["part"] == "arm_l"
    missing = vs.apply_overrides(regions, rlab, [{"point": [90, 30], "part": "arm_r"},
                                                 {"point": [60, 30], "part": "leg_l"}])
    assert regions[1]["part"] == "arm_r" and missing == ["[60, 30]"]
    pimg = vs.part_image(seg, regions, rlab)
    assert pimg[30, 90] == vs.SLICE_PARTS.index("arm_r") + 1


def test_draw_cuts_splits_a_region():
    fg = np.ones((50, 50), bool)
    line = np.zeros((50, 50), bool)
    line2 = vs.draw_cuts(line, [[25, 0, 25, 49]])
    lab, _ = vs.enclosed_regions(fg, line2)
    assert lab[25, 5] != lab[25, 45]


def test_slice_layer_order():
    o = vs.SLICE_Z
    chain = ["back_hair", "leg_l", "body", "arm_l", "side_hair_l", "head_skin", "eye_ref_l",
             "side_hair_r", "hair_top", "bangs", "ribbon", "flower", "ahoge"]
    assert [o.index(n) for n in chain] == sorted(o.index(n) for n in chain)
    assert set(o) == set(vs.SLICE_PARTS)


# ---------------------------------------------------------------- 第 2 段：切片

def test_apply_splits_moves_pixels_above_polyline():
    p = np.full((40, 40), vs.pid("bangs"), np.int32)
    out = vs.apply_splits(p, [{"part": "bangs", "above": "hair_top", "polyline": [[0, 10], [39, 20]]}])
    assert out[5, 0] == vs.pid("hair_top") and out[15, 0] == vs.pid("bangs")
    assert out[15, 39] == vs.pid("hair_top") and out[25, 39] == vs.pid("bangs")


def test_boundary_line_goes_to_upper_part():
    """head_skin（下）和 bangs（上）之间的线归 bangs；head_skin 另一侧的外轮廓线归 head_skin。"""
    H, W = 30, 60
    pimg = np.zeros((H, W), np.int32)
    pimg[:, :28] = vs.pid("head_skin")
    pimg[:, 32:] = vs.pid("bangs")
    line = np.zeros((H, W), bool)
    line[:, 28:32] = True               # 交界线
    line[:, :3] = True                  # head_skin 左边的外轮廓
    fg = np.ones((H, W), bool)
    P = vs.own_lines(pimg, line, fg, np.zeros((H, W), bool))
    assert (P[:, 28:32] == vs.pid("bangs")).all()
    assert (P[:, :3] == vs.pid("head_skin")).all()


def _two_part_scene():
    """左半 head_skin（皮肤色）、右半 bangs（发色），中间一条交界线归 bangs。"""
    H, W = 40, 80
    rgb = np.zeros((H, W, 3), np.uint8)
    rgb[:, :40] = (250, 225, 220)
    rgb[:, 40:] = (240, 200, 210)
    rgb[:, 38:42] = (70, 30, 25)
    P = np.zeros((H, W), np.int32)
    P[:, :38] = vs.pid("head_skin")
    P[:, 38:] = vs.pid("bangs")
    line = np.zeros((H, W), bool)
    line[:, 38:42] = True
    alpha = np.full((H, W), 255.0, np.float32)
    return rgb, P, line, alpha


def test_cut_slices_recompose_exactly_and_lower_part_bleeds_under():
    rgb, P, line, alpha = _two_part_scene()
    feats = {n: np.zeros(P.shape, bool) for n in ("eye_ref_l", "eye_ref_r", "mouth_ref")}
    sl = vs.cut_slices(rgb, alpha, P, line, feats)
    canvas = Image.new("RGBA", (P.shape[1], P.shape[0]), (255, 255, 255, 255))
    for n in vs.SLICE_Z:
        if n in sl:
            img, (x, y) = sl[n]
            layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            layer.paste(img, (x, y))
            canvas.alpha_composite(layer)
    out = np.asarray(canvas.convert("RGB")).astype(int)
    assert np.abs(out - rgb.astype(int)).max() <= 1
    skin, (x, _) = sl["head_skin"]
    assert x + skin.width > 38               # 皮肤往 bangs 下面延伸了几像素
    assert np.asarray(skin)[20, 38 - x, 3] > 0


def test_head_skin_erase_fills_feature_with_skin():
    rgb, P, line, alpha = _two_part_scene()
    rgb = rgb.copy()
    rgb[15:25, 10:20] = (200, 90, 20)       # “眼睛”
    P = P.copy()
    feats = {n: np.zeros(P.shape, bool) for n in ("eye_ref_l", "eye_ref_r", "mouth_ref")}
    feats["eye_ref_l"][13:27, 8:22] = True
    P[feats["eye_ref_l"]] = vs.pid("eye_ref_l")
    sl = vs.cut_slices(rgb, alpha, P, line, feats)
    skin, (x, y) = sl["head_skin"]
    a = np.asarray(skin).astype(int)
    patch = a[15 - y:25 - y, 10 - x:20 - x]
    assert (patch[..., 3] == 255).all()
    assert np.abs(patch[..., :3] - np.array([250, 225, 220])).max() < 12   # 补成了皮肤色
    eye, _ = sl["eye_ref_l"]
    assert np.asarray(eye)[..., 3].max() == 255                            # 原眼睛另存


def test_clean_strays_reassigns_far_edge_strip():
    P = np.zeros((100, 100), np.int32)
    P[10:60, 10:60] = vs.pid("side_hair_l")
    P[70:95, 10:90] = vs.pid("leg_l")
    P[95:97, 10:90] = vs.pid("side_hair_l")     # 腿外侧的一条细边，归错成了左鬓发
    outside = np.zeros_like(P, bool)
    outside[97:] = True
    out = vs.clean_strays(P, outside)
    assert (out[95:97, 10:90] == vs.pid("leg_l")).all()
    assert (out[10:60, 10:60] == vs.pid("side_hair_l")).all()


def test_committed_rig_v2_is_consistent():
    import json
    from tools import v3_extract as vx
    if not vx.RIG_FILE.exists():
        import pytest
        pytest.skip("rig.json 还没生成")
    rig = json.loads(vx.RIG_FILE.read_text(encoding="utf-8"))
    if rig.get("version") != 2:
        import pytest
        pytest.skip("不是 v2")
    for n, p in rig["parts"].items():
        assert (vx.OUT / p["file"]).exists(), n
        assert p["layer"] in rig["layers"], n
        assert p["source"] in ("ref_slice", "gpt_underlay", "gpt_expression_diff"), n
    L = rig["layers"]
    assert L.index("side_hair_l") < L.index("head_skin") < L.index("side_hair_r")
    assert L.index("hair_top") < L.index("bangs")
    assert rig["faces"]["smug"] == {"face": "smug"}
    # 表情层在刘海、头顶之下，脸之上
    assert L.index("head_skin") < L.index("face") < L.index("hair_top") < L.index("bangs")
    for n, p in rig["parts"].items():
        if p["layer"] == "face":
            assert p["slot"] == "face" and p["variant"] in rig["slots"]["face"], n
    assert ["side_hair_l", "side_hair_r"] in rig["mirror"]["swap_layers"]
    for k in ("neck", "shoulder_l", "shoulder_r", "hip_l", "hip_r", "ahoge_root", "flower_root",
              "ribbon_root", "bangs_root", "side_hair_l_root", "side_hair_r_root"):
        assert k in rig["pivots"], k


# ---------------------------------------------------------------- 差分表情

def test_extract_expression_only_face_near_features():
    H, W = 80, 120
    ref = np.full((H, W, 3), 240, np.uint8)
    expr = ref.copy()
    face = np.zeros((H, W), bool)
    face[10:70, 10:80] = True
    zone = np.zeros((H, W), bool)
    zone[10:70, 10:60] = True
    expr[30:40, 20:35] = (60, 20, 20)        # 脸上五官附近：要
    expr[30:40, 65:75] = (60, 20, 20)        # 脸上但不在五官附近（如重画的细线）：不要
    expr[30:40, 90:110] = (60, 20, 20)       # 脸外（如头顶的星星、刘海）：不要
    img, (x, y) = vs.extract_expression(ref, expr, face, zone)
    a = np.zeros((H, W))
    a[y:y + img.height, x:x + img.width] = np.asarray(img)[..., 3]
    assert a[35, 27] == 255
    assert a[35, 70] == 0 and a[35, 100] == 0
    assert 0 < a[35, 35 + vs.EXPR_GROW] < 255 or a[35, 35 + vs.EXPR_GROW] == 255   # 外扩了
    assert a[35, 35 + vs.EXPR_GROW + 4] < 255                                        # 边缘羽化


def test_extract_expression_corrects_global_tint():
    H, W = 60, 60
    ref = np.full((H, W, 3), 230, np.uint8)
    expr = np.full((H, W, 3), 220, np.uint8)  # GPT 整体偏暗 10
    expr[20:30, 20:30] = (60, 20, 20)
    face = np.ones((H, W), bool)
    img, (x, y) = vs.extract_expression(ref, expr, face, face)
    px = np.asarray(img)[25 - y + 6, 25 - x]  # 改动范围内、紧挨原五官的皮肤
    assert abs(int(px[0]) - 230) <= 2


def test_relabel_by_expressions_moves_consistently_changed_hair_to_feature():
    H, W = 40, 60
    P = np.full((H, W), vs.pid("head_skin"), np.int32)
    P[15:25, 10:20] = vs.pid("eye_ref_l")
    P[15:25, 20:24] = vs.pid("bangs")         # 紧挨眼睛、被分给刘海的眼角
    P[0:5, 40:60] = vs.pid("bangs")           # 真正的刘海
    rgb = np.full((H, W, 3), 230, np.uint8)
    exprs = {}
    for i in range(7):
        e = rgb.copy()
        e[15:25, 10:24] = (50, 20, 20)        # 每张都改了眼睛（含眼角）
        if i < 3:
            e[0:5, 40:60] = (50, 20, 20)      # 刘海只在少数几张里被重画
        exprs[str(i)] = e
    out = vs.relabel_by_expressions(P, rgb, exprs)
    assert (out[15:25, 20:24] == vs.pid("eye_ref_l")).all()
    assert (out[0:5, 40:60] == vs.pid("bangs")).all()
