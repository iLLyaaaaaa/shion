"""S9 tools/v3_scene.py 分区的测试：合成图，不依赖 raw 素材。"""
import numpy as np
from PIL import Image, ImageDraw

from tools import v3_scene as vsc

BROWN = (70, 30, 25)
WOOD = (200, 115, 75)      # 床/桌的木色
SKIN = (253, 221, 212)


def _scene():
    """白底上左边一块木色（家具）、右边一块皮肤色（角色），中间隔着一条棕色描线。"""
    im = Image.new("RGB", (240, 140), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([10, 20, 110, 120], fill=WOOD, outline=BROWN, width=4)
    d.rectangle([107, 20, 230, 120], fill=SKIN, outline=BROWN, width=4)   # 两块共用中间一条描线
    return np.asarray(im)


def _blocks():
    rgb = _scene()
    fg = vsc.foreground(rgb)
    ids, line, blocks = vsc.segment_blocks(rgb, fg)
    return rgb, fg, ids, line, blocks


def test_guess_class_wood_vs_everything_else():
    assert vsc.guess_class((194, 112, 73)) == "furniture"      # 床架
    assert vsc.guess_class((230, 155, 100)) == "furniture"     # 桌面
    assert vsc.guess_class((253, 136, 72)) == "char"           # 被子/头发的橙
    assert vsc.guess_class((253, 221, 212)) == "char"          # 皮肤
    assert vsc.guess_class((77, 57, 78)) == "char"             # 制服
    assert vsc.guess_class((129, 56, 38)) == "char"            # 深棕：不是木色
    assert vsc.guess_class((138, 106, 106), [293, 946, 1236, 947]) == "furniture"   # 1 像素高的地面线
    assert vsc.guess_class((138, 106, 106), [293, 900, 1236, 947]) == "char"


def test_two_regions_get_two_ids_and_guesses():
    rgb, fg, ids, line, blocks = _blocks()
    assert [b["id"] for b in blocks] == [1, 2]
    by_area = {b["id"]: b for b in blocks}
    # 编号按面积从大到小：右边的皮肤块更大
    assert by_area[1]["guess"] == "char" and by_area[2]["guess"] == "furniture"
    assert ids[70, 60] == 2 and ids[70, 170] == 1
    assert ids[0, 0] == 0                                       # 背景
    assert (ids[fg] > 0).all()                                  # 描线和碎块都并进了编号块


def test_classify_defaults_and_flip():
    rgb, fg, ids, line, blocks = _blocks()
    char = vsc.classify(fg, ids, line, blocks)
    assert char[70, 170] and not char[70, 60]
    flipped = vsc.classify(fg, ids, line, blocks, {"flip": [2]})
    assert flipped[70, 60] and flipped[70, 170]
    both = vsc.classify(fg, ids, line, blocks, {"flip": [1]})
    assert not both[70, 170] and not both[70, 60]


def test_force_polygons_win_over_the_guess():
    rgb, fg, ids, line, blocks = _blocks()
    box = [[40, 40], [80, 40], [80, 100], [40, 100]]
    forced = vsc.classify(fg, ids, line, blocks, {"force_char": [box]})
    assert forced[70, 60] and not forced[30, 30]                # 只有多边形里的木色块变角色
    box2 = [[140, 40], [200, 40], [200, 100], [140, 100]]
    forced = vsc.classify(fg, ids, line, blocks, {"force_furniture": [box2]})
    assert not forced[70, 170] and forced[30, 150]


def test_border_line_belongs_to_the_character():
    rgb, fg, ids, line, blocks = _blocks()
    char = vsc.classify(fg, ids, line, blocks)
    seam = [(y, x) for y in range(30, 110) for x in range(104, 116) if line[y, x]]
    assert seam
    assert all(char[y, x] for y, x in seam)                     # 家具和角色之间的描线整条归角色
    # 家具另一侧的外轮廓离角色远，仍是家具
    assert not char[70, 11]


def test_overview_size_and_numbers(tmp_path):
    rgb, fg, ids, line, blocks = _blocks()
    char = vsc.classify(fg, ids, line, blocks)
    image = vsc.overview(rgb, fg, ids, blocks, char, 1.0)
    assert image.size == (rgb.shape[1] + vsc.MARGIN, rgb.shape[0] + vsc.MARGIN)
    a = np.asarray(image)
    # 角色块偏蓝、家具块偏红
    assert a[vsc.MARGIN + 100, vsc.MARGIN + 200, 2] > a[vsc.MARGIN + 100, vsc.MARGIN + 200, 0]
    assert a[vsc.MARGIN + 100, vsc.MARGIN + 30, 0] > a[vsc.MARGIN + 100, vsc.MARGIN + 30, 2]


# ---- 生成出来的真实资源（assets/sprites/v3/scenes/，进 git）----
import json
import re
from pathlib import Path

SCENES_DIR = vsc.SCENES_DIR
REQUIRED = ("file", "mask", "size", "anchor_x", "ground_y", "char_box", "head_scale", "head_box", "head_top",
            "mouth", "zones", "breath_gain", "source", "source_sha256")


def _data():
    return json.loads(vsc.SCENES_JSON.read_text(encoding="utf-8"))


def _arrays(info):
    image = np.asarray(Image.open(SCENES_DIR / info["file"]).convert("RGBA"))
    mask = np.asarray(Image.open(SCENES_DIR / info["mask"]).convert("L")) > 127
    return image, mask


def test_scenes_json_has_the_three_scenes_with_every_field():
    data = _data()
    assert data["states"] == {"collapse": "collapse", "bed": "bed", "desk": "desk"}
    assert set(data["scenes"]) == {"collapse", "bed", "desk"}
    for name, info in data["scenes"].items():
        assert all(key in info for key in REQUIRED), name
        assert set(info["zones"]) == {"cheek", "crown"} and info["zones"]["cheek"] and info["zones"]["crown"]
    assert "z_anchor" in data["scenes"]["bed"]
    assert "z_anchor" not in data["scenes"]["desk"] and "z_anchor" not in data["scenes"]["collapse"]


def test_image_and_mask_agree_and_the_mask_is_inside_the_picture():
    for name, info in _data()["scenes"].items():
        image, mask = _arrays(info)
        assert image.shape[:2][::-1] == tuple(info["size"]) and mask.shape == image.shape[:2], name
        assert mask.any(), name
        assert (image[..., 3][mask] >= vsc.CHAR_MIN_ALPHA).all(), name      # 角色遮罩只落在可见像素上
        x0, y0, x1, y1 = info["char_box"]
        ys, xs = np.nonzero(mask)
        assert (x0, y0, x1, y1) == (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)


def test_furniture_pixels_only_where_there_is_furniture():
    scenes = _data()["scenes"]
    assert scenes["collapse"]["furniture_pixels"] < 300          # 没有家具；只剩角色边缘的零星抗锯齿
    assert scenes["bed"]["furniture_pixels"] > 50000
    assert scenes["desk"]["furniture_pixels"] > 50000


def test_ground_is_the_lowest_opaque_row_and_the_anchor_is_centered():
    for name, info in _data()["scenes"].items():
        image, _ = _arrays(info)
        rows = np.nonzero((image[..., 3] >= vsc.CHAR_MIN_ALPHA).any(axis=1))[0]
        assert info["ground_y"] == rows.max() + 1 == image.shape[0], name
        assert abs(info["anchor_x"] - image.shape[1] / 2) <= 0.5


def test_zone_centers_sit_on_the_character_and_special_points_inside_the_picture():
    for name, info in _data()["scenes"].items():
        image, mask = _arrays(info)
        h, w = mask.shape
        for key, ellipses in info["zones"].items():
            for cx, cy, rx, ry in ellipses:
                assert mask[int(cy), int(cx)], (name, key)
                assert rx > 20 and ry > 20
        points = [info["head_top"], info["mouth"]] + ([info["z_anchor"]] if "z_anchor" in info else [])
        for x, y in points:
            assert -50 <= x <= w + 50 and -50 <= y <= h, (name, x, y)
        assert mask[int(info["mouth"][1]), int(info["mouth"][0])], name            # 嘴在角色身上


def test_head_width_matches_the_standing_pose():
    standing = vsc.standing_head_box()
    sw = standing[2] - standing[0]
    for name, info in _data()["scenes"].items():
        ratio = (info["head_box"][2] - info["head_box"][0]) / sw
        assert 0.92 <= ratio <= 1.08, (name, ratio)
        assert info["head_scale"] == info["head_scale_measured"] or "head_scale" in vsc.load_map()[name]


def test_source_hashes_are_recorded_and_match_when_raw_exists():
    for name, info in _data()["scenes"].items():
        assert re.fullmatch(r"[0-9a-f]{64}", info["source_sha256"])
        if (vsc.RAW / vsc.SOURCES[name]).exists():
            assert vsc.source_hash(name) == info["source_sha256"], name


def test_build_is_reproducible_when_raw_exists(tmp_path):
    if not all((vsc.RAW / f).exists() for f in vsc.SOURCES.values()):
        return
    standing = vsc.standing_head_box()
    info, image, mask = vsc.build_scene("bed", vsc.load_map(), standing[2] - standing[0])
    saved = _data()["scenes"]["bed"]
    assert info["size"] == saved["size"] and info["char_pixels"] == saved["char_pixels"]
    assert np.array_equal(np.asarray(mask) > 127, _arrays(saved)[1])
