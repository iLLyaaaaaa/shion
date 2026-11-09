"""V3 第 0 步（改方案）：可见零件直接从 ref.png 切。

GPT 零件是重画的，拼起来和 ref 差别大。这里改成：
- 静止时看得见的部分全部从 ref.png 按线稿切出来；
- GPT 零件只做“垫底”（后发、头部底色、身体），动起来时才露出；
- 表情：在脸部切片上擦掉原眼睛和嘴，再叠 face_sheet 的零件（原眼睛和嘴另存为“得意脸”默认款）。

用法：
  python -m tools.v3_slice regions   自动分区，生成编号总览图和 slice_map 草稿（第一个停点）
  python -m tools.v3_slice slice     切片、擦除五官、垫底、写 rig.json v2，生成拼图对比（第二个停点）

分区思路：线稿（深棕）围出的封闭区域在身体、手臂、腿上分得很干净，但头部的发丝末端不闭合，
整个头连成一块。所以先用已有的 GPT 零件对位结果（build/v3/places.json）在 ref 上放“种子”，
再以线稿为墙做分水岭（scipy.ndimage.watershed_ift），把连成一块的头部沿着线切开。
最终区域 = 分水岭结果 ∩ 封闭区域，逐块编号给用户确认归属。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as nd

from tools import v3_extract as vx

ROOT = vx.ROOT
OUT = vx.OUT
BUILD = vx.BUILD
SLICE_MAP = OUT / "slice_map.json"

LINE_MAX = 110       # 线稿：max(RGB) < LINE_MAX
LINE_RB = 8          # 线稿：R - B >= LINE_RB（深棕；制服的深蓝 B >= R，不算线）
MIN_REGION = 30      # 小于这个面积的封闭区域当作线稿
NUMBER_MIN = 30      # 编号的最小区域面积

# 切片零件。这个列表的顺序是“放种子”的顺序（重叠处后放的赢），也是零件编号图里的编号，
# 改了会改变分区结果，所以不要动；图层顺序另见 SLICE_Z。
# 鼓脸颊和脸之间没有线，切不开，按用户的列表并在头部皮肤（head_skin）里。
# hair_top 没有种子，是从 bangs 里沿发际线切出来的（slice_map.json 的 splits）。
SLICE_PARTS = ["back_hair", "leg_l", "leg_r", "body", "arm_l", "arm_r", "head_skin",
               "eye_ref_l", "eye_ref_r", "mouth_ref", "side_hair_l", "side_hair_r",
               "bangs", "ribbon", "flower", "ahoge", "hair_top"]
# 图层顺序（从下到上，2026-11-05 用户确认）：左鬓发整片在脸后，右鬓发有几缕盖在脸上，
# 所以 side_hair_l < head_skin < side_hair_r，鼓脸颊（在 head_skin 里）自然盖在左鬓发上。
SLICE_Z = ["back_hair", "leg_l", "leg_r", "body", "arm_l", "arm_r", "side_hair_l", "head_skin",
           "eye_ref_l", "eye_ref_r", "mouth_ref", "side_hair_r", "hair_top", "bangs",
           "ribbon", "flower", "ahoge"]
PART_COLORS = {
    "back_hair": (150, 90, 200), "leg_l": (60, 160, 230), "leg_r": (20, 100, 200), "body": (80, 80, 90),
    "arm_l": (40, 200, 160), "arm_r": (20, 140, 100), "head_skin": (250, 200, 120),
    "eye_ref_l": (255, 0, 0), "eye_ref_r": (200, 0, 60), "mouth_ref": (255, 0, 200),
    "side_hair_l": (120, 220, 60), "cheek_puff_l": (255, 140, 0), "side_hair_r": (60, 150, 30),
    "bangs": (230, 60, 120), "ribbon": (0, 200, 220), "flower": (255, 220, 0), "ahoge": (130, 60, 20),
    "hair_top": (255, 150, 200),
}
SEED_ERODE = {"eye_ref_l": 1, "eye_ref_r": 1, "mouth_ref": 1, "ahoge": 6, "cheek_puff_l": 6}
DEFAULT_ERODE = 12


# ---------------------------------------------------------------- 线稿与封闭区域

LINE_BLACK = 45      # 接近纯黑的像素（有些地方的轮廓是黑的，不偏棕）也算线，除非明显偏蓝
HOLE_WHITE = 235     # 人物内部、没分到零件的大块近白区域（如两腿之间）算背景
HOLE_MIN = 500


def line_mask(rgb: np.ndarray, fg: np.ndarray) -> np.ndarray:
    """深棕线稿 + 接近纯黑的线。制服、鞋子的深蓝（B 明显大于 R）不算线。"""
    r, b = rgb[..., 0].astype(int), rgb[..., 2].astype(int)
    mx = rgb.max(axis=2)
    m = ((mx < LINE_MAX) & (r - b >= LINE_RB)) | ((mx < LINE_BLACK) & (b - r < 10))
    return nd.binary_closing(m & fg, iterations=1) & fg


def enclosed_regions(fg: np.ndarray, line: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """线稿以外、人物以内的四连通区域。太小的碎块并进线稿。返回 (区域标号, 新线稿)。"""
    lab, n = nd.label(fg & ~line)
    sizes = np.bincount(lab.ravel(), minlength=n + 1)
    small = sizes < MIN_REGION
    small[0] = False
    line = line | small[lab]
    lab[small[lab]] = 0
    return lab, line


# ---------------------------------------------------------------- 种子

def _footprint(img: Image.Image, place: dict, size) -> np.ndarray:
    return np.asarray(vx.render(img, place, size))[..., 3] > 128


def _rows(img: Image.Image, y0: float, y1: float) -> Image.Image:
    """只保留零件图 [y0, y1) 比例范围内的行。"""
    a = np.asarray(img).copy()
    h = a.shape[0]
    a[: int(h * y0)] = 0
    a[int(h * y1):] = 0
    return Image.fromarray(a)


def seed_footprints(parts: dict, places: dict, rig: dict | None, size) -> dict[str, np.ndarray]:
    """各切片零件在 ref 上的大致范围（用 GPT 零件的对位结果）。"""
    fp = {}
    simple = {"back_hair": "back_hair", "leg_l": "leg_l", "leg_r": "leg_r", "body": "body",
              "arm_l": "arm_l", "arm_r": "arm_r", "head_skin": "head_base", "side_hair_l": "side_hair_l",
              "side_hair_r": "side_hair_r", "bangs": "bangs", "ahoge": "ahoge",
              "eye_ref_l": "eye_half_l", "eye_ref_r": "eye_half_r", "mouth_ref": "mouth_cat"}
    for k, src in simple.items():
        if src in parts and src in places:
            fp[k] = _footprint(parts[src], places[src], size)
    # 花饰零件 = 花朵 + 飘带：上 45% 当花朵，55% 以下当飘带
    if "flower" in parts and "flower" in places:
        fp["flower"] = _footprint(_rows(parts["flower"], 0.0, 0.45), places["flower"], size)
        fp["ribbon"] = _footprint(_rows(parts["flower"], 0.55, 1.0), places["flower"], size)
    # 鼓脸颊：按上一轮在头部底色里找到的鼓包范围
    cut = (rig or {}).get("cheek_puff", {}).get("cut")
    if cut and "head_base" in parts:
        a = np.asarray(parts["head_base"]).copy()
        a[: cut["top"]] = 0
        a[cut.get("bottom", a.shape[0]):] = 0
        a[:, cut["cut_x"]:] = 0
        fp["cheek_puff_l"] = _footprint(Image.fromarray(a), places["head_base"], size)
    return fp


def make_markers(fp: dict[str, np.ndarray], fg: np.ndarray, line: np.ndarray,
                 extra_seeds: dict | None = None) -> np.ndarray:
    """种子标号：按图层从下到上画，重叠处归上层。背景是 -1。只在非线稿的人物像素上放种子。"""
    markers = np.zeros(fg.shape, np.int32)
    for i, name in enumerate(SLICE_PARTS, start=1):
        if name not in fp:
            continue
        m = nd.binary_erosion(fp[name], iterations=SEED_ERODE.get(name, DEFAULT_ERODE))
        markers[m & fg & ~line] = i
    for name, pts in (extra_seeds or {}).items():
        i = SLICE_PARTS.index(name) + 1
        for x, y in pts:
            markers[max(0, y - 3): y + 4, max(0, x - 3): x + 4] = i
    markers[~fg] = -1
    return markers


def segment(rgb: np.ndarray, fg: np.ndarray, line: np.ndarray, markers: np.ndarray) -> np.ndarray:
    """以线稿为墙的分水岭。返回每个像素的零件编号（1..len(SLICE_PARTS)，背景 0）。"""
    gray = rgb.astype(np.float32).mean(axis=2)
    grad = np.hypot(nd.sobel(gray, 0), nd.sobel(gray, 1))
    cost = np.clip(grad / 8, 0, 120)
    cost[line] = 255
    out = nd.watershed_ift(cost.astype(np.uint8), markers, structure=np.ones((3, 3)))
    out[~fg] = 0
    out[out < 0] = 0
    return out


def fill_unassigned(seg: np.ndarray, fg: np.ndarray, rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """分水岭没分到零件的人物像素：大块近白的算背景（人物内部的空洞），其余就近归给相邻零件。
    返回 (seg, fg)。"""
    un = fg & (seg == 0)
    lab, n = nd.label(un)
    fg = fg.copy()
    if n:
        white = rgb.min(axis=2) >= HOLE_WHITE
        areas = np.bincount(lab.ravel(), minlength=n + 1)
        wfrac = np.bincount(lab.ravel(), weights=white.ravel(), minlength=n + 1) / np.maximum(areas, 1)
        hole = (areas >= HOLE_MIN) & (wfrac > 0.9)
        hole[0] = False
        fg[hole[lab]] = False
        seg = seg.copy()
        seg[hole[lab]] = 0
    rest = fg & (seg == 0)
    if rest.any() and (seg > 0).any():
        _, (iy, ix) = nd.distance_transform_edt(seg == 0, return_indices=True)
        seg = seg.copy()
        seg[rest] = seg[iy[rest], ix[rest]]
    return seg, fg


def split_regions(enclosed: np.ndarray, seg: np.ndarray) -> tuple[list[dict], np.ndarray]:
    """封闭区域 ∩ 分水岭零件 → 小区域。代表点取离区域边界最远的像素。按从上到下、从左到右编号。
    返回 (区域列表, 区域标号图)；标号图里第 i 个区域的像素值为 i+1，太小没编号的为 0。"""
    key = enclosed.astype(np.int64) * 64 + seg
    key[enclosed == 0] = 0
    regions, masks = [], []
    for k in np.unique(key):
        if k == 0:
            continue
        lab, n = nd.label(key == k)
        objs = nd.find_objects(lab)
        for j in range(1, n + 1):
            sl = objs[j - 1]
            m = lab[sl] == j
            area = int(m.sum())
            if area < NUMBER_MIN:
                continue
            y0, x0 = sl[0].start, sl[1].start
            dt = nd.distance_transform_edt(np.pad(m, 1))[1:-1, 1:-1]
            py, px = np.unravel_index(int(np.argmax(dt)), dt.shape)
            regions.append({"point": [int(x0 + px), int(y0 + py)], "area": area,
                            "part": SLICE_PARTS[int(k % 64) - 1] if k % 64 else None,
                            "bbox": [int(x0), int(y0), int(sl[1].stop), int(sl[0].stop)]})
            masks.append((sl, m))
    order = sorted(range(len(regions)), key=lambda i: (regions[i]["point"][1] // 40, regions[i]["point"][0]))
    rlab = np.zeros(seg.shape, np.int32)
    out = []
    for new, i in enumerate(order, start=1):
        r = regions[i]
        r["id"] = f"R{new:03d}"
        sl, m = masks[i]
        rlab[sl][m] = new
        out.append(r)
    return out, rlab


def apply_overrides(regions: list[dict], rlab: np.ndarray, overrides: list[dict]) -> list[str]:
    """按代表点把区域改归属。返回对不上任何区域的条目（提示用）。"""
    missing = []
    for o in overrides:
        x, y = o["point"]
        i = int(rlab[y, x]) if 0 <= y < rlab.shape[0] and 0 <= x < rlab.shape[1] else 0
        if i == 0:
            missing.append(o.get("note") or str(o["point"]))
            continue
        regions[i - 1]["part"] = o["part"]
    return missing


def part_image(seg: np.ndarray, regions: list[dict], rlab: np.ndarray) -> np.ndarray:
    """最终的零件编号图：编号区域按区域归属，其余（线稿、太小的区域）先按分水岭结果。"""
    pimg = seg.copy()
    lut = np.zeros(len(regions) + 1, np.int32)
    for i, r in enumerate(regions, start=1):
        lut[i] = SLICE_PARTS.index(r["part"]) + 1 if r["part"] in SLICE_PARTS else 0
    has = rlab > 0
    pimg[has] = lut[rlab[has]]
    return pimg


# ---------------------------------------------------------------- 总览图

def overview(rgb: np.ndarray, line: np.ndarray, seg: np.ndarray, regions: list[dict],
             box=None, scale: float = 1.0, min_label_area: int = 0) -> Image.Image:
    base = rgb.astype(np.float32).mean(axis=2, keepdims=True).repeat(3, axis=2) * 0.45 + 140
    col = np.zeros_like(base)
    for i, name in enumerate(SLICE_PARTS, start=1):
        col[seg == i] = PART_COLORS[name]
    has = seg > 0
    img = base.copy()
    img[has] = base[has] * 0.4 + col[has] * 0.6
    img[line] = (40, 25, 25)
    im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
    if box:
        im = im.crop(box)
    ox, oy = (box[0], box[1]) if box else (0, 0)
    if scale != 1:
        im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
    d = ImageDraw.Draw(im)
    f = vx._font(max(11, int(13 * scale)))
    for r in regions:
        if r["area"] < min_label_area:
            continue
        x, y = r["point"]
        if box and not (box[0] <= x < box[2] and box[1] <= y < box[3]):
            continue
        tx, ty = (x - ox) * scale, (y - oy) * scale
        d.text((tx, ty), r["id"][1:], fill=(0, 0, 0), font=f, anchor="mm",
               stroke_width=2, stroke_fill=(255, 255, 255))
    return im


def legend() -> Image.Image:
    f = vx._font(18)
    im = Image.new("RGB", (260, 30 * len(SLICE_PARTS) + 10), (255, 255, 255))
    d = ImageDraw.Draw(im)
    for i, name in enumerate(SLICE_PARTS):
        y = 8 + i * 30
        d.rectangle([8, y, 34, y + 22], fill=PART_COLORS[name], outline=(0, 0, 0))
        d.text((44, y + 1), name, fill=(0, 0, 0), font=f)
    return im


def load_ref():
    rgb = np.asarray(Image.open(vx.RAW / "ref.png").convert("RGB"))
    fg = vx.remove_white_bg(rgb)[..., 3] > 128
    return rgb, fg


def draw_cuts(line: np.ndarray, cuts: list) -> np.ndarray:
    """手工切线：在线稿上画 3 px 宽的线段，把跨零件的区域切开。"""
    if not cuts:
        return line
    im = Image.fromarray(np.zeros(line.shape, np.uint8))
    d = ImageDraw.Draw(im)
    for x0, y0, x1, y1 in cuts:
        d.line([(x0, y0), (x1, y1)], fill=255, width=3)
    return line | (np.asarray(im) > 0)


def run_regions(slice_map: dict | None = None) -> dict:
    rgb, fg = load_ref()
    sm = slice_map or {}
    line = draw_cuts(line_mask(rgb, fg), sm.get("cuts", [])) & fg
    enclosed, line = enclosed_regions(fg, line)
    parts = vx.load_parts()
    places = json.loads((BUILD / "places.json").read_text(encoding="utf-8"))["places"]
    rig = json.loads(vx.RIG_FILE.read_text(encoding="utf-8")) if vx.RIG_FILE.exists() else None
    size = (rgb.shape[1], rgb.shape[0])
    fp = seed_footprints(parts, places, rig, size)
    markers = make_markers(fp, fg, line, sm.get("seeds"))
    seg = segment(rgb, fg, line, markers)
    seg, fg = fill_unassigned(seg, fg, rgb)
    enclosed[~fg] = 0
    line &= fg
    regions, rlab = split_regions(enclosed, seg)
    for r in regions:
        r["auto"] = r["part"]
    missing = apply_overrides(regions, rlab, sm.get("overrides", []))
    if missing:
        print("!! 这些改归属条目没对上任何区域：", missing)
    pimg = part_image(seg, regions, rlab)
    return {"rgb": rgb, "fg": fg, "line": line, "enclosed": enclosed, "seg": seg, "regions": regions,
            "rlab": rlab, "pimg": pimg}


def cmd_regions() -> None:
    sm = json.loads(SLICE_MAP.read_text(encoding="utf-8")) if SLICE_MAP.exists() else {}
    res = run_regions(sm)
    rgb, line, pimg, regions = res["rgb"], res["line"], res["pimg"], res["regions"]
    BUILD.mkdir(parents=True, exist_ok=True)
    full = overview(rgb, line, pimg, regions, min_label_area=150)
    lg = legend()
    canvas = Image.new("RGB", (full.width + lg.width + 10, full.height), (255, 255, 255))
    canvas.paste(full, (0, 0))
    canvas.paste(lg, (full.width + 10, 10))
    canvas.save(BUILD / "slice_overview.png")
    # 头部放大图：范围取刘海、花饰、呆毛、头部皮肤的外框再外扩一些
    hx0, hy0, hx1, hy1 = vx._bbox(np.isin(pimg, [SLICE_PARTS.index(n) + 1 for n in
                                                ("bangs", "head_skin", "flower", "ahoge")]))
    box = (max(0, hx0 - 150), max(0, hy0 - 10), min(rgb.shape[1], hx1 + 150), min(rgb.shape[0], hy1 + 120))
    overview(rgb, line, pimg, regions, box=box, scale=1.6).save(BUILD / "slice_overview_head.png")
    draft = {"_note": "区域归属（regions 是当前结果，只读参考）。要改归属就在 overrides 里加 {point, part}；"
                      "cuts: [[x0,y0,x1,y1], ...] 手工切线；seeds: {零件名: [[x,y], ...]} 追加种子点。",
             "regions": [{k: r[k] for k in ("id", "point", "area", "part", "auto")} for r in regions],
             "overrides": sm.get("overrides", []), "cuts": sm.get("cuts", []), "seeds": sm.get("seeds", {})}
    (BUILD / "slice_map_draft.json").write_text(json.dumps(draft, indent=1, ensure_ascii=False), encoding="utf-8")
    counts = {}
    for r in regions:
        counts[r["part"]] = counts.get(r["part"], 0) + 1
    print(f"{len(regions)} regions; per part: {counts}")


# ================================================================ 第 2 段：切片

LINE_OWN_R = 7       # 线稿像素归属：看半径这么多以内有哪些零件，取图层最高的
BLEED = 3            # 下层零件在切口处往上层下面延伸的像素
SLICES = OUT / "slices"
UNDERLAYS = OUT / "underlays"
HEAD_GROUP = ["side_hair_l", "head_skin", "eye_ref_l", "eye_ref_r", "mouth_ref", "side_hair_r",
              "hair_top", "bangs", "ribbon", "flower", "ahoge"]


def pid(name: str) -> int:
    return SLICE_PARTS.index(name) + 1


def zrank() -> np.ndarray:
    """零件编号 → 图层高低（0 = 背景）。"""
    r = np.zeros(len(SLICE_PARTS) + 1, np.int32)
    for z, name in enumerate(SLICE_Z, start=1):
        r[pid(name)] = z
    return r


def polyline_y(poly: list, xs: np.ndarray) -> np.ndarray:
    """折线在各 x 处的 y（两端以外取端点的 y）。"""
    px = np.array([p[0] for p in poly], float)
    py = np.array([p[1] for p in poly], float)
    o = np.argsort(px)
    return np.interp(xs, px[o], py[o])


def apply_splits(pimg: np.ndarray, splits: list) -> np.ndarray:
    """按折线把一个零件切成两个：折线以上的像素改归 above（如 bangs 的头顶部分 → hair_top）。"""
    pimg = pimg.copy()
    H, W = pimg.shape
    yy, xx = np.mgrid[0:H, 0:W]
    for s in splits:
        cut_y = polyline_y(s["polyline"], np.arange(W))[None, :]
        m = (pimg == pid(s["part"])) & (yy < cut_y)
        pimg[m] = pid(s["above"])
    return pimg


SKIN_TOL = 28        # 和皮肤/腮红中位色的 RGB 距离小于这个算“像皮肤”


def feature_masks(pimg: np.ndarray, line: np.ndarray, fp: dict, rgb: np.ndarray) -> dict[str, np.ndarray]:
    """原眼睛和嘴的范围，按颜色圈（GPT 零件比 ref 的五官小，按它圈不全；眼眶下沿的线有缺口，
    按封闭区域也圈不全）：
    - 先从脸上（离五官远的地方）取皮肤和腮红的中位色；
    - 在 GPT 半眯眼/猫嘴对位范围附近，“不像皮肤”的像素（虹膜、眼白、阴影、线）里，
      和五官核心连在一起的那些就是五官；嘴里的舌头接近腮红色，所以嘴只排除皮肤色；
    - 紧贴头发的线稿不擦（刘海压在眼睛上的那几缕的轮廓线归头发）。"""
    face = np.isin(pimg, [pid(n) for n in ("head_skin", "eye_ref_l", "eye_ref_r", "mouth_ref")])
    hair = np.isin(pimg, [pid(n) for n in ("bangs", "hair_top", "side_hair_l", "side_hair_r")]) & ~line
    over_eye_hair = np.isin(pimg, [pid(n) for n in ("bangs", "hair_top")]) & ~line   # 盖在眼睛上的刘海
    near_hair_line = nd.binary_dilation(over_eye_hair, iterations=9)
    hair_label = np.isin(pimg, [pid(n) for n in ("bangs", "hair_top", "side_hair_l", "side_hair_r")])
    feat_core = fp["eye_ref_l"] | fp["eye_ref_r"] | fp["mouth_ref"]
    away = face & ~line & ~nd.binary_dilation(feat_core, iterations=30)
    c = rgb.astype(np.float32)
    rg = c[..., 0] - c[..., 1]
    skin_med = np.median(c[away & (rg < 45)], axis=0)
    blush_sel = away & (rg >= 45)
    blush_med = np.median(c[blush_sel], axis=0) if blush_sel.any() else skin_med
    d_skin = np.linalg.norm(c - skin_med, axis=-1)
    d_blush = np.linalg.norm(c - blush_med, axis=-1)
    out = {}
    for name, grow in (("eye_ref_l", 60), ("eye_ref_r", 60), ("mouth_ref", 12)):
        # 只保护头发的轮廓线：已分给头发的线、离刘海 9 px 以内的线不擦（鬓发旁边的眼尾线要擦）；
        # 脸上的像素照常可以擦
        allowed = face | (line & ~near_hair_line & ~hair_label)
        reach = nd.binary_dilation(fp[name], iterations=grow) & allowed
        skinlike = d_skin < SKIN_TOL
        if name != "mouth_ref":
            skinlike |= d_blush < SKIN_TOL
        cand = reach & ~skinlike
        lab, n = nd.label(cand, structure=np.ones((3, 3)))
        core = nd.binary_dilation(fp[name], iterations=3)
        ids = np.unique(lab[core & cand])
        m = np.isin(lab, ids[ids > 0])
        m = nd.binary_fill_holes(m)
        m = nd.binary_dilation(m, iterations=2) & allowed
        out[name] = m
    return out


def own_lines(pimg: np.ndarray, line: np.ndarray, fg: np.ndarray, fixed: np.ndarray) -> np.ndarray:
    """线稿归属：交界处的线归图层高的一边（遮挡者的轮廓线），零件内部的线归自己。
    fixed 为 True 的像素（眼、嘴）不改。"""
    P = pimg.copy()
    fill = fg & ~line
    todo = line & fg & ~fixed
    rank = zrank()
    for name in SLICE_Z:                       # 从下往上，上层覆盖
        own = (P == pid(name)) & fill
        if not own.any():
            continue
        near = nd.distance_transform_edt(~own) <= LINE_OWN_R
        P[todo & near] = pid(name)
    rest = todo & ~nd.binary_dilation(fill, iterations=LINE_OWN_R)
    if rest.any():                             # 很粗的线中心：就近
        _, (iy, ix) = nd.distance_transform_edt(~fill, return_indices=True)
        P[rest] = P[iy[rest], ix[rest]]
    del rank
    return P


STRAY_MAX = 300     # 每个零件里，面积小于这个、又不是最大块的连通碎块，改归周围的零件
STRAY_EDGE_MAX = 3000  # 外轮廓细条的面积上限
STRAY_FAR = 60      # 外轮廓细条离零件主体的最小距离


def clean_strays(P: np.ndarray, outside: np.ndarray | None = None) -> np.ndarray:
    """分水岭偶尔会把远处的像素分给某个零件，零件一动它们就会跟着飞走。两类改归周围最多的那个零件：
    - 小碎块：不是该零件最大的一块，面积 < STRAY_MAX；
    - 外轮廓细条：外轮廓线外侧那圈灰色抗锯齿只能经过轮廓线被“淹”到，常被随机分给某个零件
      （如腿边、呆毛旁的细条归了左鬓发）。不是最大的一块、面积 < STRAY_EDGE_MAX、
      有两成以上像素紧贴人物外面（outside）、又离该零件主体 STRAY_FAR 以上的，也算
      （右鬓发被飘带隔开的那几块离主体近，不受影响）。"""
    P = P.copy()
    near_out = nd.binary_dilation(outside, iterations=3) if outside is not None else None
    for name in SLICE_PARTS:
        m = P == pid(name)
        lab, n = nd.label(m, structure=np.ones((3, 3)))
        if n <= 1:
            continue
        sizes = np.bincount(lab.ravel())
        sizes[0] = 0
        biggest = int(np.argmax(sizes))
        edge_frac = (np.bincount(lab.ravel(), weights=near_out.ravel(), minlength=n + 1) / np.maximum(sizes, 1)
                     if near_out is not None else np.zeros(n + 1))
        dist_main = nd.distance_transform_edt(lab != biggest)
        for j in range(1, n + 1):
            if j == biggest:
                continue
            far = dist_main[lab == j].min() > STRAY_FAR
            stray = sizes[j] < STRAY_MAX or (sizes[j] < STRAY_EDGE_MAX and edge_frac[j] > 0.2 and far)
            if not stray:
                continue
            comp = lab == j
            ring = nd.binary_dilation(comp, iterations=2) & ~comp & (P > 0)
            vals = P[ring]
            vals = vals[vals != pid(name)]
            if len(vals):
                P[comp] = np.bincount(vals).argmax()
            else:                      # 四周只有背景（外轮廓外侧的零星淡像素）：归最近的其他零件
                other = (P > 0) & (P != pid(name))
                if other.any():
                    _, (iy, ix) = nd.distance_transform_edt(~other, return_indices=True)
                    ys, xs = np.nonzero(comp)
                    P[ys, xs] = P[iy[ys, xs], ix[ys, xs]]       # 每个像素各自归最近的
    return P




STRAND_FEAT_GAP = 15  # 离原五官这么近的暗红细线不当刘海发丝（那是眼睑线的抗锯齿）
STRAND_MIN = 30       # 发丝线的最小面积
STRAND_GAP = 8        # 两条发丝线之间 2*8 px 以内的窄缝算发丝内部
STRAND_MAX_CHANGED = 3  # 五官附近的暗线，7 张差分图里最多这么多张变了，就算刘海发丝（眼睑线几乎每张都变）


def relabel_strands(P: np.ndarray, rgb: np.ndarray, line: np.ndarray, change_count: np.ndarray | None = None) -> np.ndarray:
    """刘海里有几缕很细的发丝（如左眼上方“Λ”形那两条）只画了暗红色的线，颜色不够黑，
    不算线稿，和皮肤一起被分进了 head_skin；差分表情会把它们盖掉（teary 左眼上方的白斜线）。
    把 head_skin 里和刘海连着、离原五官较远的暗红细线改归 bangs。"""
    c = rgb.astype(np.int16)
    # 暗红色的线：要足够暗（腮红的粉色 min 约 165，不能算进来）
    reddish = (c.min(axis=-1) < 120) & (c.max(axis=-1) < 200) & (c[..., 0] - c[..., 2] > 20)
    skin = P == pid("head_skin")
    feat = np.isin(P, [pid(n) for n in ("eye_ref_l", "eye_ref_r", "mouth_ref")])
    near_feat = nd.binary_dilation(feat, iterations=STRAND_FEAT_GAP)
    cand = skin & (reddish | line) & ~near_feat
    if change_count is not None:
        # 五官附近的暗线：眼睑线在差分图里几乎每张都变；刘海发丝线大多数张不变（只有个别几张被 GPT 重画）。
        # 变的张数少的当发丝
        cand |= skin & (reddish | line) & near_feat & ~feat & (change_count <= STRAND_MAX_CHANGED)
    bangs = np.isin(P, [pid("bangs"), pid("hair_top")])
    lab, n = nd.label(cand, structure=np.ones((3, 3)))
    if n == 0:
        return P
    touch = np.unique(lab[nd.binary_dilation(bangs, iterations=2) & cand])
    sizes = np.bincount(lab.ravel())
    ids = [t for t in touch if t > 0 and sizes[t] >= STRAND_MIN]
    P = P.copy()
    P[np.isin(lab, ids)] = pid("bangs")
    # 发丝内部：两条发丝线之间的窄缝（如“Λ”形那缕的里面）也是头发，不是脸。对刘海做闭运算，
    # 补上的 head_skin 像素（离原五官较远的）改归 bangs，差分表情就不会替换它（GPT 常把这里画成白色高光）
    bangs = P == pid("bangs")
    closed = nd.binary_closing(bangs, iterations=STRAND_GAP)
    inner = closed & (P == pid("head_skin")) & ~nd.binary_dilation(feat, iterations=STRAND_FEAT_GAP)
    P[inner] = pid("bangs")
    return P


def nearest_color(rgb: np.ndarray, src: np.ndarray) -> np.ndarray:
    """每个像素取 src 里最近像素的颜色。"""
    _, (iy, ix) = nd.distance_transform_edt(~src, return_indices=True)
    return rgb[iy, ix]


def cut_slices(rgb: np.ndarray, alpha: np.ndarray, P: np.ndarray, line: np.ndarray,
               features: dict, seams: list | None = None) -> dict[str, tuple[Image.Image, tuple[int, int]]]:
    """按零件编号图切出各零件（RGBA，紧贴外框裁剪）。返回 {零件: (图, (x, y))}。

    - 下层零件在和上层零件的交界处往上层下面延伸 BLEED 像素（颜色取最近的本零件像素），alpha 逐渐变淡；
      静止时被上层盖住，动起来时不露白缝。
    - seams 里列出的、没有线的人工切口（如发际线 hair_top / bangs）：上层那一边的边缘做 1 像素半透明，
      和下层延伸出来的同色像素融在一起。其他交界都有线，不做（否则会把线旁边的抗锯齿像素也弄淡）。
    - 头部皮肤：原眼睛、嘴的范围用周围皮肤补上（擦除五官）。
    """
    rank = zrank()
    Z = rank[P]
    out = {}
    for name in SLICE_Z:
        own = P == pid(name)
        if not own.any():
            continue
        x0, y0, x1, y1 = vx._bbox(own)
        pad = BLEED + 2
        x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
        x1, y1 = min(P.shape[1], x1 + pad), min(P.shape[0], y1 + pad)
        sl = (slice(y0, y1), slice(x0, x1))
        o = own[sl]
        a = np.where(o, alpha[sl], 0).astype(np.float32)
        col = rgb[sl].astype(np.float32)
        if name == "head_skin":                 # 擦除原五官：用周围皮肤补
            hole = np.zeros_like(o)
            for f in ("eye_ref_l", "eye_ref_r", "mouth_ref"):
                hole |= features[f][sl]
            # 补色来源只取明亮的皮肤像素：线旁边偏暗的抗锯齿像素不算，否则会补出深色污迹
            skin_src = o & ~line[sl] & ~hole & (rgb[sl].min(axis=-1) > 170)
            # 整块先换成最近的皮肤色再模糊，模糊时不会把旁边的线混进来
            filled = nearest_color(col, skin_src)
            blur = np.stack([nd.gaussian_filter(filled[..., c], 2.5) for c in range(3)], -1)
            col = np.where(hole[..., None], blur, col)
            a = np.where(hole, 255.0, a)
            o = o | hole

        # 往上层下面延伸
        d = nd.distance_transform_edt(~o)
        upper = (Z[sl] > rank[pid(name)]) & (alpha[sl] > 0)
        bleed = (d > 0) & (d <= BLEED) & upper
        if bleed.any():
            ext = nearest_color(col, o)
            col = np.where(bleed[..., None], ext, col)
            a = np.where(bleed, 255.0 * (1 - (d - 1) / BLEED), a)
        # 人工切口：上层边缘半透明
        for pa, pb in (seams or []):
            other = pb if name == pa else pa if name == pb else None
            if other and rank[pid(name)] > rank[pid(other)]:
                edge = o & nd.binary_dilation(P[sl] == pid(other), iterations=1)
                a = np.where(edge, a * 0.5, a)
        # 外轮廓的半透明像素在 ref 里已经和白底混过：颜色换成最近的不透明像素，
        # 再反推 alpha，使它叠在白底上还原 ref 原来的颜色（否则白色算两遍，边缘发亮）
        ring = o & (alpha[sl] < 250) & (alpha[sl] > 0)
        if ring.any():
            solid = o & (alpha[sl] >= 250)
            if solid.any():
                c0 = nearest_color(col, solid)
                pix = rgb[sl].astype(np.float32)
                den = 255 - c0
                ok = den > 20
                est = np.where(ok, (255 - pix) / np.maximum(den, 1), 0)
                n_ok = np.maximum(ok.sum(-1), 1)
                aa = np.clip(est.sum(-1) / n_ok, 0, 1) * 255
                col = np.where(ring[..., None], c0, col)
                a = np.where(ring, aa, a)
        rgba = np.dstack([np.clip(col, 0, 255), np.clip(a, 0, 255)]).astype(np.uint8)
        img = Image.fromarray(rgba)
        bb = img.getbbox()
        out[name] = (img.crop(bb), (x0 + bb[0], y0 + bb[1]))
    return out


def coverage_above(slices: dict, layer: str, size) -> np.ndarray:
    """图层 layer 及以上所有切片叠起来的不透明度（0..1）。"""
    W, H = size
    keep = np.ones((H, W), np.float32)            # 透过率
    for n in SLICE_Z[SLICE_Z.index(layer):]:
        if n not in slices:
            continue
        img, (x, y) = slices[n]
        a = np.asarray(img)[..., 3].astype(np.float32) / 255
        sub = keep[y:y + a.shape[0], x:x + a.shape[1]]
        sub *= 1 - a[: sub.shape[0], : sub.shape[1]]
    return 1 - keep


def make_underlays(parts: dict, places: dict, P: np.ndarray, alpha: np.ndarray, size,
                   slices: dict) -> dict:
    """GPT 零件垫底：按原来的对位放好，只保留落在对应切片组范围内、并且被上面的切片完全盖住的部分
    （切片的半透明羽化边下面不放）。这样静止时一定看不见，动起来时才从缝里露出来。"""
    groups = {
        "back_hair_under": ("back_hair", HEAD_GROUP + ["back_hair"]),
        "head_under": ("head_base", HEAD_GROUP),
        "body_under": ("body", ["body", "arm_l", "arm_r"]),
    }
    out = {}
    for name, (src, members) in groups.items():
        covered = coverage_above(slices, UNDER_Z[name], size) >= 0.999
        m = np.isin(P, [pid(n) for n in members]) & covered
        layer = np.asarray(vx.render(parts[src], places[src], size)).copy()
        layer[..., 3] = np.where(m, layer[..., 3], 0)
        img = Image.fromarray(layer)
        bb = img.getbbox()
        if bb:
            out[name] = (img.crop(bb), (bb[0], bb[1]))
    return out


UNDER_Z = {"back_hair_under": "back_hair", "body_under": "body", "head_under": "side_hair_l"}  # 垫在谁下面


# ---------------------------------------------------------------- 差分表情

EXPRESSIONS = ["neutral", "happy", "surprised", "teary", "angry", "sleep", "dizzy"]
EXPR_DIR = OUT / "expressions"
# Ref-space eye windows; pixels outside belong to mouth (including eyebrows).
# Keeping a disjoint partition preserves even the original feathered pixels.
EYE_WINDOWS = {
    "neutral": ((310, 462, 505, 565), (550, 445, 755, 555)),
    "happy": ((310, 496, 490, 574), (565, 459, 775, 535)),
    "surprised": ((310, 450, 495, 590), (565, 426, 775, 580)),
    "teary": ((310, 452, 495, 600), (565, 440, 775, 580)),
    "angry": ((310, 480, 495, 590), (565, 440, 775, 580)),
    "sleep": ((310, 501, 495, 570), (565, 483, 775, 540)),
    "dizzy": ((310, 487, 495, 570), (565, 456, 775, 545)),
}
EYE_TOP_LINES = {
    "teary": ((310, 502, 495, 450), (565, 440, 775, 485)),
    "angry": ((310, 480, 495, 490), (565, 482, 775, 443)),
}


def split_expression(image: Image.Image, origin, windows, top_lines=None, regions=None):
    """Partition RGBA pixels without feathering twice or changing their colors."""
    rgba = np.asarray(image)
    yy, xx = np.indices(rgba.shape[:2])
    xx, yy = xx + origin[0], yy + origin[1]
    assigned = np.zeros(xx.shape, bool)
    out = {}
    for index, (role, box) in enumerate(zip(("eye_l", "eye_r"), windows)):
        x0, y0, x1, y1 = box
        mask = (xx >= x0) & (xx < x1) & (yy >= y0) & (yy < y1) & ~assigned
        if regions:
            region = Image.new('1',image.size)
            ImageDraw.Draw(region).polygon([(px-origin[0],py-origin[1]) for px,py in regions[role]],fill=1)
            for points,width in regions.get('brow_paths',[]):
                ImageDraw.Draw(region).line([(px-origin[0],py-origin[1]) for px,py in points],fill=0,width=width,joint='curve')
            mask = np.asarray(region,dtype=bool)&~assigned
        if top_lines and not regions:
            ax, ay, bx, by = top_lines[index]
            mask &= yy >= ay + (xx - ax) * (by - ay) / (bx - ax)
        assigned |= mask
        a = rgba.copy()
        a[~mask] = 0
        im = Image.fromarray(a)
        bb = im.getbbox()
        if bb is None:
            raise ValueError(f"empty {role}")
        out[role] = (im.crop(bb), (origin[0] + bb[0], origin[1] + bb[1]))
    a = rgba.copy()
    a[assigned] = 0
    im = Image.fromarray(a)
    bb = im.getbbox()
    if bb is None:
        raise ValueError("empty mouth/brow layer")
    out["mouth"] = (im.crop(bb), (origin[0] + bb[0], origin[1] + bb[1]))
    return out


def split_rig_expressions(rig: dict, folder: Path = OUT) -> dict:
    """Also callable on step-0 assets: no raw access or reslicing required."""
    for variant in rig["slots"]["face"]:
        if variant == "smug":
            for name, role in (("eye_ref_l", "eye_l"), ("eye_ref_r", "eye_r"),
                               ("mouth_ref", "mouth")):
                p = rig["parts"][name]
                p["role"] = role
                if role.startswith("eye"):
                    p["blink_pivot"] = [p["x"] + p["size"][0] / 2, p["y"] + p["size"][1] - 1]
            continue
        name = f"expr_{variant}"
        old = rig["parts"].get(name)
        # Original composite is retained as deterministic splitting input.
        if old is None:
            old = rig.get("expression_sources", {}).get(variant)
            if old is None:
                continue
        rig.setdefault("expression_sources", {})[variant] = old
        with Image.open(folder / old["file"]) as im:
            children = split_expression(im.convert("RGBA"), (old["x"], old["y"]), EYE_WINDOWS[variant],
                                        EYE_TOP_LINES.get(variant), old.get('regions'))
        rig["parts"].pop(name, None)
        for role, (im, (x, y)) in children.items():
            child = f"{name}_{role}"
            file = f"expressions/{child}.png"
            vx.save_png(im, folder / file)
            p = {**old, "file": file, "x": x, "y": y, "size": list(im.size), "role": role}
            if role.startswith("eye"):
                p["blink_pivot"] = [x + im.width / 2, y + im.height - 1]
            rig["parts"][child] = p
    rig["notes"]["blink"] = "eye_l/r 绕 blink_pivot 压缩；mouth 含眉，不参与眨眼。原 expr_*.png 保留作拆分输入。"
    return rig


def cmd_split_expressions():
    rig = json.loads(vx.RIG_FILE.read_text(encoding="utf-8"))
    split_rig_expressions(rig)
    vx.RIG_FILE.write_text(json.dumps(rig, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("split expression sublayers; original slices and underlays unchanged")

EXPR_T = 40          # 和 ref 的逐像素差（RGB 三通道取最大）超过这个算“改过”
EXPR_ZONE = 70       # 只在原眼睛、嘴外扩这么多的范围里找（含眉毛；脸边缘的重画细线不算）
EXPR_MIN = 40        # 小于这个面积的改动碎块不要
EXPR_GROW = 3        # 改动范围外扩
EXPR_FEATHER = 1.2   # 边缘羽化（高斯 sigma）
EXPR_HAIR_GAP = 5    # 离头发这么近、差异又低于 EXPR_T 的像素不提取


EXPR_CONSISTENT = 6  # 五官附近被分给头发的像素：7 张差分图里至少这么多张都变了，就当成原来的五官


def load_expressions(shape) -> dict[str, np.ndarray]:
    out = {}
    for name in EXPRESSIONS:
        f = vx.RAW / f"expr_{name}.png"
        if not f.exists():
            print(f"!! 没有 {f.name}，跳过")
            continue
        e = np.asarray(Image.open(f).convert("RGB"))
        if e.shape != shape:
            raise ValueError(f"{f.name} 尺寸 {e.shape} 和 ref {shape} 不一样")
        out[name] = e
    return out


def relabel_by_expressions(P: np.ndarray, rgb: np.ndarray, exprs: dict) -> np.ndarray:
    """原眼睛紧挨头发的那一圈（眼睑线、外眼角的眼白和虹膜）常被分给刘海或鬓发，擦不掉也提取不到。
    用差分图判断：五官附近、被分给头发的像素，如果几乎每张差分图里都变了（眼睛每张都换；
    GPT 重画刘海是每张随机的，不会张张都变），就改归最近的原五官。"""
    if len(exprs) < EXPR_CONSISTENT:
        return P
    feat_ids = [pid(n) for n in ("eye_ref_l", "eye_ref_r", "mouth_ref")]
    feat = np.isin(P, feat_ids)
    hair = np.isin(P, [pid(n) for n in ("bangs", "hair_top", "side_hair_l", "side_hair_r")])
    zone = nd.binary_dilation(feat, iterations=25)
    cand = zone & hair
    if not cand.any():
        return P
    ref = rgb.astype(np.int16)
    count = np.zeros(P.shape, np.int16)
    for e in exprs.values():
        count += (np.abs(e.astype(np.int16) - ref).max(axis=-1) > EXPR_T) & cand
    move = cand & (count >= EXPR_CONSISTENT)
    # 只要和原五官连在一起的
    lab, _ = nd.label(move | feat, structure=np.ones((3, 3)))
    ids = np.unique(lab[feat])
    move &= np.isin(lab, ids[ids > 0])
    P = P.copy()
    _, (iy, ix) = nd.distance_transform_edt(~feat, return_indices=True)
    P[move] = P[iy[move], ix[move]]
    return P


def extract_expression(ref: np.ndarray, expr: np.ndarray, face: np.ndarray, zone: np.ndarray,
                       hair: np.ndarray | None = None, feat: np.ndarray | None = None):
    """从 GPT 只改了眼和嘴的整图里，取出脸上改过的部分（眼、眉、嘴）。

    - 只看脸（head_skin + 原五官）的范围，而且只在五官附近（zone）：GPT 顺手改的刘海、
      头顶的星星、全图重画留下的细线差异都不要；
    - 差异像素去噪、连起来、补洞、外扩 EXPR_GROW，再羽化；
    - GPT 图整体色调和 ref 略有差别：用改动范围外面一圈“没改过”的皮肤算出平均色差，校正回来，
      不然羽化边上会有一圈色差。
    返回 (RGBA 图, (x, y))，没有改动时返回 None。"""
    d = np.abs(expr.astype(np.float32) - ref.astype(np.float32)).max(axis=-1)
    cand = (d > EXPR_T) & face & zone
    cand = nd.binary_opening(cand, iterations=1)
    lab, n = nd.label(cand, structure=np.ones((3, 3)))
    if n == 0:
        return None
    sizes = np.bincount(lab.ravel())
    keep = sizes >= EXPR_MIN
    keep[0] = False
    m = keep[lab]
    m = nd.binary_closing(m, iterations=3)
    # 补洞只补和原五官范围重叠的洞（眼睛内部和 ref 颜色接近的地方，原五官已被擦掉，必须盖住）；
    # 其他被改动像素围起来的洞不补（如 teary 左眼上方两缕刘海之间 GPT 画的白色高光）
    if feat is None:
        m = nd.binary_fill_holes(m)
    else:
        holes = nd.binary_fill_holes(m) & ~m
        hl, hn = nd.label(holes)
        if hn:
            ids = np.unique(hl[holes & nd.binary_dilation(feat, iterations=2)])
            m |= np.isin(hl, ids[ids > 0])
    m = nd.binary_dilation(m, iterations=EXPR_GROW) & face
    # 紧挨头发、和 ref 差异又不大的像素不要：GPT 顺手重画的刘海（带白色高光）会被上面的闭运算/补洞带进来
    if hair is not None:
        m &= ~(nd.binary_dilation(hair, iterations=EXPR_HAIR_GAP) & (d < EXPR_T))
    ring = nd.binary_dilation(m, iterations=8) & ~m & face & (d < 20)
    off = np.median(ref[ring].astype(np.float32) - expr[ring].astype(np.float32), axis=0) if ring.sum() > 50 else 0
    col = np.clip(expr.astype(np.float32) + off, 0, 255)
    a = nd.gaussian_filter(m.astype(np.float32), EXPR_FEATHER)
    a = np.maximum(a, nd.binary_erosion(m, iterations=2))
    # 和 ref 差异大的像素一律完全不透明，羽化只发生在它们外面：
    # 否则 head_skin 里原眼睑线的抗锯齿残留会从半透明的羽化边下面透出来（右眼上方那排淡点）。
    # 这样不用改 head_skin，得意脸保持和 ref 一致
    a = np.maximum(a, (m & (d > EXPR_T)).astype(np.float32))
    a[~face] = 0
    rgba = np.dstack([col, a * 255]).astype(np.uint8)
    img = Image.fromarray(rgba)
    bb = img.getbbox()
    if not bb:
        return None
    return img.crop(bb), (bb[0], bb[1])


def extract_all_expressions(rgb: np.ndarray, P: np.ndarray, expr_imgs: dict, line: np.ndarray) -> dict:
    face = np.isin(P, [pid(n) for n in ("head_skin", "eye_ref_l", "eye_ref_r", "mouth_ref")])
    feat = np.isin(P, [pid(n) for n in ("eye_ref_l", "eye_ref_r", "mouth_ref")])
    zone = nd.binary_dilation(feat, iterations=EXPR_ZONE)
    hair = np.isin(P, [pid(n) for n in ("bangs", "hair_top", "side_hair_l", "side_hair_r")])
    out = {}
    for name, expr in expr_imgs.items():
        r = extract_expression(rgb, expr, face, zone, hair, feat)
        if r:
            out[f"expr_{name}"] = r
    return out


def slice_pivots(slices: dict, splits: list | None = None) -> dict:
    """转轴（ref 坐标），都按切片形状估。"""
    def mask(n):
        img, (x, y) = slices[n]
        return np.asarray(img)[..., 3] > 128, x, y

    def top_band_center(n, frac):
        m, x, y = mask(n)
        rows = np.nonzero(m.any(axis=1))[0]
        band = np.zeros_like(m)
        band[rows[0]: rows[0] + max(2, int(len(rows) * frac))] = True
        cx, cy = vx._centroid(m & band)
        return [round(x + cx, 1), round(y + cy, 1)]

    piv = {}
    # 脖子：头部皮肤（下巴）最下沿的中点
    m, x, y = mask("head_skin")
    rows = np.nonzero(m.any(axis=1))[0]
    xs = np.nonzero(m[rows[-1] - 2])[0]
    piv["neck"] = [round(x + float(xs.mean()), 1), round(y + float(rows[-1] - 2), 1)]
    # 肩：手臂靠身体那一侧的上角
    for n, inner_right in (("arm_l", True), ("arm_r", False)):
        m, x, y = mask(n)
        h, w = m.shape
        q = np.zeros_like(m)
        if inner_right:
            q[: h // 3, w * 2 // 3:] = True
        else:
            q[: h // 3, : w // 3] = True
        cx, cy = vx._centroid(m & q)
        piv["shoulder_" + n[-1]] = [round(x + cx, 1), round(y + cy, 1)]
    for n in ("leg_l", "leg_r"):
        piv["hip_" + n[-1]] = top_band_center(n, 0.06)
    # 呆毛根：最下面一截的中心
    m, x, y = mask("ahoge")
    rows = np.nonzero(m.any(axis=1))[0]
    band = np.zeros_like(m)
    band[rows[-1] - max(2, len(rows) // 12): rows[-1] + 1] = True
    cx, cy = vx._centroid(m & band)
    piv["ahoge_root"] = [round(x + cx, 1), round(y + cy, 1)]
    m, x, y = mask("flower")
    cx, cy = vx._centroid(m)
    piv["flower_root"] = [round(x + cx, 1), round(y + cy, 1)]
    piv["ribbon_root"] = top_band_center("ribbon", 0.08)
    # 刘海根在发际线切口上：取切口折线在刘海宽度中点处的位置（顶部一带的重心会被右高左低的切口带偏）
    bimg, (bx, by) = slices["bangs"]
    cx = bx + bimg.width / 2
    piv["bangs_root"] = ([round(cx, 1), round(float(polyline_y(splits[0]["polyline"], np.array([cx]))[0]), 1)]
                         if splits else top_band_center("bangs", 0.08))
    piv["side_hair_l_root"] = top_band_center("side_hair_l", 0.08)
    piv["side_hair_r_root"] = top_band_center("side_hair_r", 0.08)
    return piv


PARENT_V2 = {"body": None, "leg_l": "body", "leg_r": "body", "arm_l": "body", "arm_r": "body",
             "head_skin": "body", "back_hair": "head_skin", "side_hair_l": "head_skin",
             "side_hair_r": "head_skin", "hair_top": "head_skin", "bangs": "hair_top",
             "flower": "head_skin", "ribbon": "flower", "ahoge": "hair_top",
             "eye_ref_l": "head_skin", "eye_ref_r": "head_skin", "mouth_ref": "head_skin",
             "back_hair_under": "head_skin", "head_under": "head_skin", "body_under": "body"}
PIVOT_V2 = {"head_skin": "neck", "arm_l": "shoulder_l", "arm_r": "shoulder_r", "leg_l": "hip_l",
            "leg_r": "hip_r", "ahoge": "ahoge_root", "flower": "flower_root", "ribbon": "ribbon_root",
            "bangs": "bangs_root", "side_hair_l": "side_hair_l_root", "side_hair_r": "side_hair_r_root",
            "hair_top": "neck", "back_hair": "neck"}


def layers_v2() -> list[str]:
    """完整图层表：切片 + 垫底 + 表情层 face（原眼睛、嘴 = 得意脸；差分表情各一张，互斥）。
    face 在 head_skin 之上、右鬓发 / hair_top / bangs 之下，刘海盖在眼睛前面。"""
    out = []
    for n in SLICE_Z:
        for u, above in UNDER_Z.items():
            if above == n:
                out.append(u)
        if n == "eye_ref_l":
            out.append("face")
        elif n in ("eye_ref_r", "mouth_ref"):
            continue
        else:
            out.append(n)
    return out


def layer_v2(name: str) -> str:
    if name in ("eye_ref_l", "eye_ref_r", "mouth_ref") or name.startswith("expr_"):
        return "face"
    return name


def run_slice() -> dict:
    sm = json.loads(SLICE_MAP.read_text(encoding="utf-8"))
    res = run_regions(sm)
    rgb, fg, line = res["rgb"], res["fg"], res["line"]
    pimg = apply_splits(res["pimg"], sm.get("splits", []))
    parts = vx.load_parts()
    places = json.loads((BUILD / "places.json").read_text(encoding="utf-8"))["places"]
    size = (rgb.shape[1], rgb.shape[0])
    rig_old = json.loads(vx.RIG_FILE.read_text(encoding="utf-8")) if vx.RIG_FILE.exists() else None
    fp = seed_footprints(parts, places, rig_old, size)
    # 原眼睛、嘴：先只把五官里非线稿的像素（虹膜、眼白、嘴里）标成五官；线稿统一交给线稿归属处理
    # ——眼睑线挨着刘海的归刘海，所以擦除五官时不会把刘海的轮廓线一起擦掉（以前右眼上方留白缺口）
    for n, m in feature_masks(pimg, line, fp, rgb).items():
        pimg[m & ~line] = pid(n)
    P = own_lines(pimg, line, fg, np.zeros(pimg.shape, bool))
    alpha = vx.remove_white_bg(rgb)[..., 3].astype(np.float32)
    # 人物内部的白色空洞（两腿之间）：和外轮廓一样按“白的程度”给 alpha，边缘的灰色抗锯齿保留，
    # 颜色归最近的零件
    _, fg0 = load_ref()
    hole = fg0 & ~fg
    if hole.any():
        alpha[hole] = np.clip((255 - rgb[hole].min(axis=1).astype(np.float32)) / (255 - 180) * 255, 0, 255)
    # 外轮廓最外圈很淡的抗锯齿像素（alpha<=128，不算“人物”）和空洞边缘：就近归给零件，不能丢
    loose = (alpha > 0) & (P == 0)
    if loose.any():
        _, (iy, ix) = nd.distance_transform_edt(P == 0, return_indices=True)
        P = P.copy()
        P[loose] = P[iy[loose], ix[loose]]
    P = clean_strays(P, outside=alpha < 128)
    expr_imgs = load_expressions(rgb.shape)
    P = relabel_by_expressions(P, rgb, expr_imgs)
    ref16 = rgb.astype(np.int16)
    change_count = sum((np.abs(e.astype(np.int16) - ref16).max(axis=-1) > EXPR_T).astype(np.int16)
                       for e in expr_imgs.values()) if expr_imgs else None
    P = relabel_strands(P, rgb, line, change_count)
    # 擦除范围 = 最终归五官的像素
    feats = {n: P == pid(n) for n in ("eye_ref_l", "eye_ref_r", "mouth_ref")}
    seams = [(x["part"], x["above"]) for x in sm.get("splits", [])]
    slices = cut_slices(rgb, alpha, P, line, feats, seams)
    unders = make_underlays(parts, places, P, alpha, size, slices)
    exprs = extract_all_expressions(rgb, P, expr_imgs, line)
    return {"rgb": rgb, "P": P, "slices": slices, "unders": unders, "parts": parts, "sm": sm,
            "alpha": alpha, "line": line, "exprs": exprs}


FACE_NAMES = ["smug"] + EXPRESSIONS


def write_rig_v2(res: dict) -> dict:
    slices, unders, exprs = res["slices"], res["unders"], res["exprs"]
    for d in (SLICES, UNDERLAYS, EXPR_DIR):
        d.mkdir(parents=True, exist_ok=True)
        for f in d.glob("*.png"):
            f.unlink()
    pivots = slice_pivots(slices, res["sm"].get("splits", []))
    layers = layers_v2()
    faces = ["smug"] + [n[len("expr_"):] for n in exprs]
    rig = {
        "version": 2,
        "canvas": [int(res["rgb"].shape[1]), int(res["rgb"].shape[0])],
        "source": "assets/sprites/raw/v3/ref.png",
        "coords": "ref 像素坐标。所有零件都是左上角 (x, y)、不缩放",
        "layers": layers,
        "parts": {},
        "slots": {"face": faces},
        "faces": {f: {"face": f} for f in faces},
        "pivots": pivots,
        "mirror": {
            "note": "屏幕另一侧时整体水平镜像。镜像头部皮肤（含左侧鼓脸颊）时，左右鬓发的上下顺序一起对调："
                    "镜像后应为 side_hair_r < head_skin < side_hair_l，鼓脸颊仍盖在它那一侧的鬓发上",
            "swap_layers": [["side_hair_l", "side_hair_r"]],
        },
        "notes": {
            "face": "表情层 face 一次只显示一款：smug = ref 原来的眼睛和嘴（eye_ref_*、mouth_ref）；"
                    "其余 expr_* 是 GPT 在 ref 上只改眼和嘴的整图，与 ref 逐像素比较后，只取脸上五官附近改过的部分。"
                    "face 在 head_skin 之上、右鬓发/hair_top/bangs 之下，刘海盖在眼睛前面",
            "head_skin": "head_skin 切片里原来的眼睛和嘴已经擦掉、用周围皮肤补上",
            "blink": "眨眼另做：以后用闭眼款或把当前表情层的眼睛纵向压缩",
            "dizzy_stars": "dizzy 头顶的星星没有提取，以后做成特效",
            "head_base_alt": "B02 为备用头部底色，不参与拼图",
            "left_right": "左右一律指画面左/右",
            "underlay": "*_under 是 GPT 零件垫底，只保留被上面切片完全盖住的部分，静止时看不见",
            "hair_top": "头顶头发随头部刚性运动，不做摆动；bangs 挂在 hair_top 上做摆动",
        },
    }

    def add(name, img, x, y, source, folder):
        vx.save_png(img, folder / f"{name}.png")
        lay = layer_v2(name)
        e = {"file": f"{folder.name}/{name}.png", "source": source, "layer": lay, "z": layers.index(lay),
             "x": int(x), "y": int(y), "size": list(img.size), "parent": PARENT_V2.get(name, "head_skin")}
        if lay == "face":
            e["slot"], e["variant"] = "face", ("smug" if name in ("eye_ref_l", "eye_ref_r", "mouth_ref")
                                              else name[len("expr_"):])
        if name in PIVOT_V2:
            e["pivot"] = PIVOT_V2[name]
        rig["parts"][name] = e

    for name, (img, (x, y)) in slices.items():
        add(name, img, x, y, "ref_slice", SLICES)
    for name, (img, (x, y)) in unders.items():
        add(name, img, x, y, "gpt_underlay", UNDERLAYS)
    for name, (img, (x, y)) in exprs.items():
        add(name, img, x, y, "gpt_expression_diff", EXPR_DIR)
    split_rig_expressions(rig)
    vx.RIG_FILE.write_text(json.dumps(rig, indent=1, ensure_ascii=False), encoding="utf-8")
    return rig


# ---------------------------------------------------------------- 拼图与对比

def load_images(rig: dict) -> dict[str, Image.Image]:
    return {n: Image.open(OUT / p["file"]).convert("RGBA") for n, p in rig["parts"].items()}


def compose_v2(rig: dict, imgs: dict, face: dict, underlays: bool = True, only: set | None = None) -> Image.Image:
    size = tuple(rig["canvas"])
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    for lay in rig["layers"]:
        for n, p in rig["parts"].items():
            if p["layer"] != lay:
                continue
            if only is not None and n not in only:
                continue
            if p["source"] == "gpt_underlay" and not underlays:
                continue
            if "slot" in p and face.get(p["slot"]) != p["variant"]:
                continue
            if "x" in p:
                layer = Image.new("RGBA", size, (0, 0, 0, 0))
                layer.paste(imgs[n], (p["x"], p["y"]))
                canvas.alpha_composite(layer)
            else:
                vx.paste_center(canvas, vx.transform(imgs[n], p["scale"], p["rot"]), p["cx"], p["cy"])
    return canvas


def diff_view(ref_rgb: np.ndarray, comp: Image.Image, fg: np.ndarray) -> tuple[Image.Image, dict]:
    c = np.asarray(vx.on_white(comp)).astype(float)
    r = ref_rgb.astype(float)
    diff = np.abs(c - r).max(axis=2)
    stats = {"mean": float(diff[fg].mean()), "p99": float(np.percentile(diff[fg], 99)),
             "max": float(diff[fg].max()), "px_over_16": int((diff[fg] > 16).sum())}
    gray = r.mean(axis=2) * 0.3 + 175
    heat = np.dstack([np.clip(gray + diff * 3, 0, 255), np.clip(gray - diff * 3, 0, 255),
                      np.clip(gray - diff * 3, 0, 255)]).astype(np.uint8)
    return Image.fromarray(heat), stats


def cut_view(res: dict, rig: dict, imgs: dict) -> Image.Image:
    """发际线切口：hair_top（粉）和 bangs（品红）着色，叠在 ref 上，旁边是 ref 原图。"""
    rgb = res["rgb"]
    P = res["P"]
    base = rgb.astype(np.float32)
    ov = base.copy()
    for n, c in (("hair_top", (255, 120, 200)), ("bangs", (60, 140, 255))):
        m = P == pid(n)
        ov[m] = base[m] * 0.45 + np.array(c) * 0.55
    poly = res["sm"]["splits"][0]["polyline"]
    xs = [p[0] for p in poly]
    box = (max(0, min(xs) - 60), max(0, min(p[1] for p in poly) - 200),
           min(rgb.shape[1], max(xs) + 60), min(rgb.shape[0], max(p[1] for p in poly) + 200))
    a = Image.fromarray(ov.astype(np.uint8)).crop(box)
    b = Image.fromarray(rgb).crop(box)
    d = ImageDraw.Draw(a)
    d.line([(x - box[0], y - box[1]) for x, y in poly], fill=(0, 200, 80), width=3)
    f = vx._font(20)
    d.text((8, 8), "hair_top (pink) / bangs (blue) / cut (green)", fill=(0, 0, 0), font=f,
           stroke_width=3, stroke_fill=(255, 255, 255))
    return vx.side_by_side([("cut", a), ("ref", b)])


def pivot_view_v2(rig: dict, imgs: dict, comp: Image.Image) -> Image.Image:
    img = vx.on_white(comp).convert("RGBA")
    d = ImageDraw.Draw(img)
    f = vx._font(22)
    for n, p in rig["parts"].items():
        if p["source"] != "ref_slice":
            continue
        w, h = p["size"]
        d.rectangle([p["x"], p["y"], p["x"] + w, p["y"] + h], outline=(60, 120, 255, 255), width=2)
    for k, (x, y) in rig["pivots"].items():
        d.ellipse([x - 8, y - 8, x + 8, y + 8], fill=(255, 0, 80, 255), outline=(255, 255, 255, 255), width=2)
        d.text((x + 10, y - 12), k, fill=(200, 0, 60, 255), font=f, stroke_width=3, stroke_fill=(255, 255, 255, 255))
    return img.convert("RGB")


def cmd_slice() -> None:
    res = run_slice()
    rig = write_rig_v2(res)
    imgs = load_images(rig)
    ref_img = Image.fromarray(res["rgb"])
    fg = res["alpha"] > 0
    comps = []
    for face in ("neutral", "smug"):
        c = compose_v2(rig, imgs, rig["faces"][face])
        comps.append((face, c))
        vx.on_white(c).save(BUILD / f"{face}.png")
    vx.side_by_side([(t, vx.on_white(c)) for t, c in comps] + [("ref", ref_img)]).save(BUILD / "compare_all.png")
    # 脸部放大：以头部皮肤为中心
    hs = rig["parts"]["head_skin"]
    cx, cy = hs["x"] + hs["size"][0] / 2, hs["y"] + hs["size"][1] / 2
    box = (int(cx - 330), int(cy - 250), int(cx + 330), int(cy + 230))
    crop = lambda im, k=1.5: im.crop(box).resize((int((box[2] - box[0]) * k), int((box[3] - box[1]) * k)), Image.LANCZOS)
    vx.side_by_side([(t, crop(vx.on_white(c))) for t, c in comps] + [("ref", crop(ref_img))]).save(BUILD / "compare_faces.png")
    # 8 种表情总览（脸部，2 行 x 4 列）
    tiles = [(f, crop(vx.on_white(compose_v2(rig, imgs, rig["faces"][f])), 1.0)) for f in rig["slots"]["face"]]
    row1, row2 = vx.side_by_side(tiles[:4]), vx.side_by_side(tiles[4:8])
    grid = Image.new("RGB", (max(row1.width, row2.width), row1.height + row2.height + 10), (255, 255, 255))
    grid.paste(row1, (0, 0))
    grid.paste(row2, (0, row1.height + 10))
    grid.save(BUILD / "expressions.png")
    # neutral：拼图 / ref / GPT 原图 expr_neutral
    raw_neutral = Image.open(vx.RAW / "expr_neutral.png").convert("RGB")
    vx.side_by_side([("neutral (composite)", crop(vx.on_white(comps[0][1]))), ("ref", crop(ref_img)),
                     ("expr_neutral (GPT)", crop(raw_neutral))]).save(BUILD / "compare_neutral.png")
    # 只用切片拼回（得意脸）与 ref 的差异
    stats = {}
    for label, und in (("slices only", False), ("with underlays", True)):
        c = compose_v2(rig, imgs, rig["faces"]["smug"], underlays=und)
        heat, st = diff_view(res["rgb"], c, fg)
        stats[label] = st
        if not und:
            vx.side_by_side([("smug (slices only)", vx.on_white(c)), ("diff x3", heat), ("ref", ref_img)]).save(
                BUILD / "recompose_diff.png")
    unders = {n for n, p in rig["parts"].items() if p["source"] == "gpt_underlay"}
    vx.side_by_side([("underlays only", vx.on_white(compose_v2(rig, imgs, {}, only=unders))),
                     ("ref", ref_img)]).save(BUILD / "underlays.png")
    pivot_view_v2(rig, imgs, comps[1][1]).save(BUILD / "pivots.png")
    cut_view(res, rig, imgs).save(BUILD / "hairline_cut.png")
    for old in ("compare_neutral_v1.png",):
        (BUILD / old).unlink(missing_ok=True)
    (BUILD / "recompose_stats.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")
    print("recompose diff (0-255, max over RGB):", json.dumps(stats))
    print(f"{len(rig['parts'])} parts in rig.json v2")


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=["regions", "slice", "split-expressions"])
    a = p.parse_args(argv)
    {"regions": cmd_regions, "slice": cmd_slice, "split-expressions": cmd_split_expressions}[a.cmd]()


if __name__ == "__main__":
    main()
