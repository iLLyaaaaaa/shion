"""tools/v3_extract.py 的测试：全部用合成图，不依赖 raw 素材。"""
import json

import numpy as np
import pytest
from PIL import Image, ImageDraw

from tools import v3_extract as vx


def _blob(w, h, color, seed=0):
    """带渐变和几个色块的椭圆零件，纹理足够做模板匹配。"""
    rng = np.random.default_rng(seed)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([0, 0, w - 1, h - 1], fill=color + (255,), outline=(40, 20, 20, 255), width=3)
    for _ in range(4):
        x, y = rng.integers(w // 5, w * 4 // 5), rng.integers(h // 5, h * 4 // 5)
        r = int(rng.integers(3, max(4, min(w, h) // 6)))
        c = tuple(int(v) for v in rng.integers(0, 255, 3))
        d.ellipse([x - r, y - r, x + r, y + r], fill=c + (255,))
    return img


def test_clean_alpha_removes_halo_and_keeps_part():
    a = np.zeros((40, 40, 4), np.uint8)
    a[..., :3] = 255
    a[..., 3] = 8                       # 整圈淡白光晕
    a[10:30, 10:30] = (200, 50, 50, 255)
    a[9, 10:30, 3] = 120                # 半透明边
    out = vx.clean_alpha(a)
    assert (out[..., 3] > 0).sum() == 20 * 20 + 20
    assert out[0, 0, 3] == 0
    assert tuple(out[9, 15, :3]) == (200, 50, 50)   # 半透明边的颜色取自最近的不透明像素


def test_components_numbered_by_rows():
    a = np.zeros((100, 200, 4), np.uint8)
    for x0, y0 in [(150, 10), (20, 12), (80, 60), (10, 65)]:
        a[y0:y0 + 20, x0:x0 + 20] = (255, 0, 0, 255)
    a[90:92, 0:3, 3] = 255             # 碎屑，面积 < MIN_AREA
    comps = vx.find_components(a, "T")
    assert [c["id"] for c in comps] == ["T01", "T02", "T03", "T04"]
    assert [c["bbox"][:2] for c in comps] == [[20, 12], [150, 10], [10, 65], [80, 60]]


def test_merge_components_and_resolve_map():
    a = np.zeros((50, 100, 4), np.uint8)
    a[10:30, 10:25] = (1, 2, 3, 255)
    a[10:30, 60:80] = (4, 5, 6, 255)
    labels = vx.label_sheet(a)
    comps = vx.find_components(a, "F")
    img, bbox = vx.merge_components(a, labels, comps)
    assert bbox == [10, 10, 80, 30] and img.size == (70, 20)
    assert np.asarray(img)[5, 30, 3] == 0      # 两块之间仍是透明的
    parts = vx.resolve_map({"parts": {"eye": ["F01", "F02"], "x": None, "m": "F03"}})
    assert parts == {"eye": ["F01", "F02"], "m": ["F03"]}
    with pytest.raises(ValueError):
        vx.resolve_map({"parts": {"a": "F01", "b": ["F01"]}})


def test_remove_white_bg_keeps_inner_white():
    rgb = np.full((60, 60, 3), 255, np.uint8)
    rgb[10:50, 10:50] = (30, 30, 30)
    rgb[25:35, 25:35] = 255             # 人物内部的白色（高光）
    out = vx.remove_white_bg(rgb)
    assert out[0, 0, 3] == 0
    assert out[30, 30, 3] == 255
    assert out[20, 20, 3] == 255


def test_local_to_ref_matches_pil_transform():
    img = Image.new("RGBA", (60, 40), (0, 0, 0, 0))
    ImageDraw.Draw(img).rectangle([0, 0, 59, 39], fill=(0, 0, 255, 255))
    img.putpixel((50, 8), (255, 0, 0, 255))
    ImageDraw.Draw(img).ellipse([47, 5, 53, 11], fill=(255, 0, 0, 255))
    place = {"cx": 150.0, "cy": 120.0, "scale": 1.5, "rot": 30.0}
    layer = np.asarray(vx.render(img, place, (300, 300)))
    red = (layer[..., 0] > 200) & (layer[..., 2] < 80) & (layer[..., 3] > 200)
    ys, xs = np.nonzero(red)
    x, y = vx.local_to_ref((50, 8), img.size, place)
    assert abs(xs.mean() - x) < 2 and abs(ys.mean() - y) < 2


def test_match_part_recovers_scale_and_position():
    part = _blob(60, 44, (230, 140, 60), seed=3)
    place = {"cx": 130.0, "cy": 95.0, "scale": 1.3, "rot": 0.0}
    canvas = Image.new("RGBA", (260, 220), (255, 255, 255, 255))
    canvas.alpha_composite(vx.render(part, place, canvas.size))
    # 再放一个不相干的东西做干扰
    canvas.alpha_composite(vx.render(_blob(50, 50, (60, 90, 200), seed=9), {"cx": 50, "cy": 170, "scale": 1, "rot": 0}, canvas.size))
    I = np.asarray(canvas.convert("RGB"), np.float32) / 255
    W = np.ones(I.shape[:2], np.float32)
    res = vx.match_part(part, I, W, scales=np.geomspace(0.8, 1.6, 15), factor=2)
    assert abs(res["scale"] / 1.3 - 1) < 0.02
    assert abs(res["cx"] - 130) <= 2 and abs(res["cy"] - 95) <= 2
    assert res["score"] > 0.9


def test_match_part_ignores_covered_pixels():
    """上层零件盖住的地方（W=0）不参与比较：被盖住一半也能找准。"""
    part = _blob(60, 60, (240, 200, 190), seed=5)
    place = {"cx": 100.0, "cy": 100.0, "scale": 1.0, "rot": 0.0}
    canvas = Image.new("RGBA", (200, 200), (255, 255, 255, 255))
    canvas.alpha_composite(vx.render(part, place, canvas.size))
    ImageDraw.Draw(canvas).rectangle([70, 60, 200, 100], fill=(120, 60, 30, 255))   # 盖住上半
    I = np.asarray(canvas.convert("RGB"), np.float32) / 255
    W = np.ones(I.shape[:2], np.float32)
    W[60:101, 70:] = 0
    res = vx.match_part(part, I, W, scales=np.geomspace(0.85, 1.15, 7), factor=2)
    assert abs(res["cx"] - 100) <= 2 and abs(res["cy"] - 100) <= 2


def test_cheek_cut_finds_bulge_and_make_cheek_feathers():
    img = Image.new("RGBA", (200, 220), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([30, 10, 190, 190], fill=(250, 220, 210, 255))      # 头
    d.ellipse([10, 130, 70, 190], fill=(250, 220, 210, 255))      # 左下鼓脸颊
    d.rectangle([100, 185, 120, 215], fill=(250, 220, 210, 255))  # 脖子
    a = np.asarray(img)[..., 3]
    cut = vx.cheek_cut(a)
    assert 140 <= cut["bulge_row"] <= 180
    assert cut["bulge_x"] <= 12
    assert 105 <= cut["top"] < cut["bulge_row"]
    assert cut["bulge_row"] < cut["bottom"] < 200
    cheek = vx.make_cheek(img, cut["top"], 80, feather=10, bottom=cut["bottom"])
    ca = np.asarray(cheek)[..., 3]
    ox, oy = cheek.info["offset"]
    assert ox + cheek.width <= 80 and oy >= cut["top"]
    assert oy + cheek.height <= cut["bottom"]
    assert ca[:, -1].max() < 40            # 右边切口羽化到接近透明
    assert ca[-1].max() < 40               # 下边也羽化
    assert ca.max() == 255


def test_neck_clip_hides_neck_below_chin():
    img = Image.new("RGBA", (200, 220), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([20, 10, 180, 190], fill=(250, 220, 210, 255))     # 头
    d.rectangle([85, 150, 115, 215], fill=(250, 220, 210, 255))  # 脖子，和下巴连在一起
    a = np.asarray(img)[..., 3] > 128
    c = vx.neck_clip(a, extra=3)
    assert c["neck_x"] == [85, 115]
    assert 150 <= c["chin_row"] < 190
    out = np.asarray(vx.clipped({"h": img}, "h", {"h": c}))[..., 3]
    assert out[c["chin_row"] + 1:, 85:116].max() == 0     # 下巴以下的脖子不画
    assert out[100, 100] == 255                           # 脸还在
    assert out[c["chin_row"] - 2, 83] == 255              # 紧贴脖子左侧的下巴还在


def test_scale_about_keeps_pivot():
    p = {"cx": 110.0, "cy": 50.0, "scale": 0.8, "rot": 0.0}
    vx.scale_about(p, 100.0, 100.0, 1.1)
    assert p["cx"] == pytest.approx(111.0) and p["cy"] == pytest.approx(45.0)
    assert p["scale"] == pytest.approx(0.88)


def test_slot_and_layer_rules():
    assert vx.slot_of("eye_half_l") == ("eye", "half", "l")
    assert vx.slot_of("eye_happy_closed_r") == ("eye", "happy_closed", "r")
    assert vx.slot_of("mouth_cat") == ("mouth", "cat", "")
    assert vx.slot_of("bangs") is None
    order = vx.LAYERS
    chain = ["back_hair", "leg_l", "body", "arm_l", "head_base", "eye_l", "mouth", "brow_l",
             "side_hair_l", "bangs", "flower", "ahoge"]
    assert [order.index(n) for n in chain] == sorted(order.index(n) for n in chain)
    assert order.index("cheek_puff_l") == order.index("side_hair_l") + 1
    assert order.index("cheek_puff_r") > order.index("side_hair_r")
    assert order.index("cheek_puff_l") < order.index("bangs")
    # 2026-11-05 调整：腮红在两侧鬓发和鼓脸颊之上、刘海之下
    for b in ("blush_l", "blush_r"):
        assert max(order.index(n) for n in ("side_hair_l", "side_hair_r", "cheek_puff_l", "cheek_puff_r")) \
            < order.index(b) < order.index("bangs")
    for n in ("eye_happy_closed_l", "brow_smug_r", "blush_strong_l", "mouth_pout"):
        assert vx.layer_of(n) in order


def test_committed_rig_is_consistent():
    """仓库里的 rig.json（若已生成）：零件文件存在、图层合法、转轴齐全。"""
    if not vx.RIG_FILE.exists():
        pytest.skip("rig.json 还没生成")
    rig = json.loads(vx.RIG_FILE.read_text(encoding="utf-8"))
    if rig.get("version", 1) >= 2:
        pytest.skip("rig.json 已升级为 v2（ref 切片），由 tests/test_v3_slice.py 检查")
    for n, p in rig["parts"].items():
        assert (vx.OUT / p["file"]).exists(), n
        assert p["layer"] in rig["layers"], n
        assert p["method"].split("+")[0] in ("match", "inferred", "derived", "override"), n
    for k in ("neck", "shoulder_l", "shoulder_r", "hip_l", "hip_r", "ahoge_root", "flower_root",
              "bangs_root", "side_hair_l_root", "side_hair_r_root"):
        assert k in rig["pivots"], k
    assert rig["cheek_puff"]["l"]["above"] == "side_hair_l"
    assert rig["cheek_puff"]["r"]["above"] == "side_hair_r"
    assert "blink" in rig["notes"]
    assert "head_base_alt" not in rig["parts"]
    t = rig["tuning"]
    for k in ("eye_scale", "eye_spread_px", "cheek_scale", "cheek_dx_px", "head_dy_px", "head_group_scale"):
        assert k in t, k
    assert "head_base" in rig["render_clip"]
