"""S9：三张整图姿势（collapse / bed / desk）的素材工具。

python -m tools.v3_scene regions [名字…]   分区编号总览（停点 A：用户确认哪些块是家具）
python -m tools.v3_scene build             生成运行时资源和 scenes.json（第 1b 步）
python -m tools.v3_scene check             对比图与数字（第 1b 步）
python -m tools.v3_scene preview           离屏窗口截图（第 3 步）

原图在 assets/sprites/raw/v3/s6/（只读、不进 git）。分区思路同 tools/v3_slice.py regions：
描线围出封闭小块 → 面积 >= MIN_BLOCK 的编号 → 按颜色预猜 角色/家具 → 用户看编号总览图改错的，
修正写进 assets/sprites/v3/scenes/scene_map.json（每个 scene 一段）：
  {"bed": {"flip": [编号…], "force_char": [[[x, y], …], …], "force_furniture": [[[x, y], …], …]}}
flip 把该编号的预猜反过来；force_* 是原图坐标的多边形，最后应用，优先级最高。
交界描线归角色：描线像素 3 像素内只要有角色，就算角色。
"""
from __future__ import annotations

import colorsys
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as nd

from shion import v3_scene as vsrt
from tools import v3_extract as vx
from tools import v3_slice as vs

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "assets" / "sprites" / "raw" / "v3" / "s6"
SCENES_DIR = ROOT / "assets" / "sprites" / "v3" / "scenes"
MAP_FILE = SCENES_DIR / "scene_map.json"
BUILD = ROOT / "build" / "v3" / "integrate" / "s9"
SOURCES = {"collapse": "collapse-pose.png", "bed": "bed-scene.png", "desk": "desk-scene.png"}

MIN_BLOCK = 400        # 面积小于这个的封闭小块不编号，并进最近的编号块
BORDER_LINE = 3        # 交界描线：这么近以内有角色，描线就算角色
OVERVIEW_MAX = 1100    # 总览图最长边（像素）
MARGIN = 34            # 总览图四周留给坐标刻度的宽度
TICK = 100             # 刻度间隔（原图像素）

# 木色：色相 14°～32°，饱和度 0.48～0.68，明度 0.68～0.96。
# 被子/头发的橙（饱和度 0.72 以上、明度 0.99）、皮肤（饱和度 0.1～0.2）都在范围外。
WOOD_HUE = (14.0, 32.0)
WOOD_SAT = (0.48, 0.68)
WOOD_VAL = (0.68, 0.96)


THIN_LINE = 3          # 包围盒短边不超过这个的细条（地面线、阴影线）预猜为家具


def guess_class(median_rgb, bbox=None) -> str:
    """区域中位色 → "furniture"（木色）或 "char"；细长的线条（短边 <= THIN_LINE）算家具。"""
    if bbox is not None and min(bbox[2] - bbox[0], bbox[3] - bbox[1]) <= THIN_LINE:
        return "furniture"
    r, g, b = (float(c) / 255 for c in median_rgb)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    h *= 360
    wood = (WOOD_HUE[0] <= h <= WOOD_HUE[1] and WOOD_SAT[0] <= s <= WOOD_SAT[1]
            and WOOD_VAL[0] <= v <= WOOD_VAL[1])
    return "furniture" if wood else "char"


def foreground(rgb: np.ndarray) -> np.ndarray:
    return vx.remove_white_bg(rgb)[..., 3] >= 128


def segment_blocks(rgb: np.ndarray, fg: np.ndarray, min_area: int = MIN_BLOCK):
    """(ids, line, blocks)。

    ids：每个前景像素所属的编号（1..n，背景 0），描线和小碎块并进最近的编号块；
    line：描线像素；blocks：每块 {id, area, bbox, point, median, guess}，按面积从大到小编号。
    """
    line = vs.line_mask(rgb, fg)
    lab, line = vs.enclosed_regions(fg, line)
    sizes = np.bincount(lab.ravel())
    sizes[0] = 0
    keep = np.flatnonzero(sizes >= min_area)
    keep = keep[np.argsort(-sizes[keep], kind="stable")]
    lut = np.zeros(len(sizes), np.int32)
    lut[keep] = np.arange(1, len(keep) + 1)
    big = lut[lab]
    if len(keep):
        idx = nd.distance_transform_edt(big == 0, return_distances=False, return_indices=True)
        ids = big[idx[0], idx[1]]
    else:
        ids = np.zeros(big.shape, np.int32)
    ids = np.where(fg, ids, 0).astype(np.int32)
    blocks = []
    for new_id in range(1, len(keep) + 1):
        mask = big == new_id
        ys, xs = np.nonzero(mask)
        x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
        crop = mask[y0:y1, x0:x1]
        depth = nd.distance_transform_edt(np.pad(crop, 1))[1:-1, 1:-1]
        py, px = np.unravel_index(int(depth.argmax()), depth.shape)
        median = np.median(rgb[mask], axis=0)
        blocks.append({"id": new_id, "area": int(mask.sum()), "bbox": [x0, y0, x1, y1],
                       "point": [x0 + int(px), y0 + int(py)],
                       "median": [int(c) for c in median], "guess": guess_class(median, [x0, y0, x1, y1])})
    return ids, line, blocks


def polygon_mask(shape, polygons) -> np.ndarray:
    image = Image.new("L", (shape[1], shape[0]), 0)
    draw = ImageDraw.Draw(image)
    for polygon in polygons:
        draw.polygon([tuple(p) for p in polygon], fill=255)
    return np.asarray(image) > 0


def classify(fg, ids, line, blocks, fix=None) -> np.ndarray:
    """角色遮罩（bool，仅前景内）。fix 是 scene_map.json 里这个 scene 的段。"""
    fix = fix or {}
    flip = set(fix.get("flip", ()))
    is_char = np.zeros(len(blocks) + 1, bool)
    for block in blocks:
        char = block["guess"] == "char"
        is_char[block["id"]] = char != (block["id"] in flip)
    char = is_char[ids] & fg
    near = nd.binary_dilation(char, iterations=BORDER_LINE)
    char |= line & fg & near                       # 交界描线归角色
    if fix.get("force_furniture"):
        char &= ~polygon_mask(fg.shape, fix["force_furniture"])
    if fix.get("force_char"):
        char |= polygon_mask(fg.shape, fix["force_char"]) & fg
    return char


# ---------------------------------------------------------------- 总览图

def overview(rgb, fg, ids, blocks, char, scale: float) -> Image.Image:
    """角色蓝、家具红，白线描编号块边界，白字编号；四周是原图坐标刻度。"""
    tint = np.zeros(rgb.shape, np.float32)
    tint[char] = (70, 130, 255)
    tint[fg & ~char] = (255, 80, 80)
    base = rgb.astype(np.float32) * 0.55 + tint * 0.45
    base[~fg] = 255
    edge = np.zeros(fg.shape, bool)
    for a, b in ((ids[:, 1:], ids[:, :-1]), (ids[1:], ids[:-1])):
        diff = (a != b) & (a > 0) & (b > 0)
        if a.shape[0] == ids.shape[0]:
            edge[:, 1:] |= diff
        else:
            edge[1:] |= diff
    base[edge] = 255
    im = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))
    size = (round(im.width * scale), round(im.height * scale))
    im = im.resize(size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (size[0] + MARGIN, size[1] + MARGIN), (255, 255, 255))
    canvas.paste(im, (MARGIN, MARGIN))
    d = ImageDraw.Draw(canvas)
    small = vx._font(13)
    big = vx._font(max(15, int(18 * scale + 8)))
    for x in range(0, rgb.shape[1], TICK):
        px = MARGIN + x * scale
        d.line([(px, MARGIN - 6), (px, MARGIN)], fill=(0, 0, 0))
        d.text((px + 2, 4), str(x), fill=(0, 0, 0), font=small)
    for y in range(0, rgb.shape[0], TICK):
        py = MARGIN + y * scale
        d.line([(MARGIN - 6, py), (MARGIN, py)], fill=(0, 0, 0))
        d.text((2, py + 2), str(y), fill=(0, 0, 0), font=small)
    for block in blocks:
        x, y = block["point"]
        d.text((MARGIN + x * scale, MARGIN + y * scale), str(block["id"]), fill=(0, 0, 0), font=big,
               anchor="mm", stroke_width=3, stroke_fill=(255, 255, 255))
    return canvas


def load_map(path: Path = MAP_FILE) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def load_source(name: str) -> np.ndarray:
    with Image.open(RAW / SOURCES[name]) as im:
        return np.asarray(im.convert("RGB"))


def analyse(name: str, fix_map: dict | None = None):
    """(rgb, fg, ids, line, blocks, char)。"""
    rgb = load_source(name)
    fg = foreground(rgb)
    ids, line, blocks = segment_blocks(rgb, fg)
    fix = (load_map() if fix_map is None else fix_map).get(name, {})
    return rgb, fg, ids, line, blocks, classify(fg, ids, line, blocks, fix)


def cmd_regions(names) -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    for name in names or SOURCES:
        rgb, fg, ids, line, blocks, char = analyse(name)
        scale = min(1.0, OVERVIEW_MAX / max(rgb.shape[:2]))
        overview(rgb, fg, ids, blocks, char, scale).save(BUILD / f"regions-{name}.png")
        flip = set(load_map().get(name, {}).get("flip", ()))
        report = []
        for block in blocks:
            final = "char" if block["guess"] == "char" else "furniture"
            if block["id"] in flip:
                final = "furniture" if final == "char" else "char"
            report.append({**block, "final": final})
        (BUILD / f"regions-{name}.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
        furniture = [b["id"] for b in report if b["final"] == "furniture"]
        print(f"{name}: {len(blocks)} 块；角色像素 {int(char.sum())}，家具像素 {int((fg & ~char).sum())}")
        print(f"  家具编号：{furniture}")
        for b in report:
            print(f"  {b['id']:3d} {b['final'][:4]:4s} area={b['area']:7d} bbox={tuple(b['bbox'])} "
                  f"median={tuple(b['median'])}")


# ---------------------------------------------------------------- 生成运行时资源（第 1b 步）

SCENES_JSON = SCENES_DIR / "scenes.json"
RIG_JSON = ROOT / "assets" / "sprites" / "v3" / "rig.json"
HEAD_PARTS = ("hair_top", "bangs", "head_skin", "side_hair_l", "side_hair_r")
CHAR_MIN_ALPHA = 8        # 缩放后 alpha 低于这个的像素不算角色
FURNITURE_GAP = 2         # 家具图里去掉角色周围这么宽的一圈（运行时同值，见 shion/v3_scene.py）
WINDOW_HEIGHTS = (160, 200, 260, 320)
SIDE_PADDING = 48         # 同 shion/v3_window.py SIDE_PADDING
SCENE_MARGIN = 16         # 同 shion/v3_scene.py extra_half_width 的余量
V2_VISIBLE_RATIO = 480 / 512


def standing_head_box() -> tuple[int, int, int, int]:
    """站姿头发整团的包围盒（rig 坐标）：hair_top、bangs、head_skin、两侧鬓发的并集。"""
    parts = json.loads(RIG_JSON.read_text(encoding="utf-8"))["parts"]
    boxes = [(parts[n]["x"], parts[n]["y"], parts[n]["x"] + parts[n]["size"][0],
              parts[n]["y"] + parts[n]["size"][1]) for n in HEAD_PARTS]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def source_hash(name: str) -> str:
    import hashlib
    return hashlib.sha256((RAW / SOURCES[name]).read_bytes()).hexdigest()


def clean_rgba(rgb: np.ndarray, alpha: np.ndarray, fg: np.ndarray) -> np.ndarray:
    """去白底后的 RGBA：不实的像素（抗锯齿一圈、背景）颜色换成最近的实心像素，缩放时不带白边。"""
    idx = nd.distance_transform_edt(~fg, return_distances=False, return_indices=True)
    colour = rgb.copy()
    soft = alpha < 255
    colour[soft] = rgb[idx[0], idx[1]][soft]
    return np.dstack([colour, alpha])


def owner_mask(fg: np.ndarray, char: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """每个可见像素属于角色还是家具；抗锯齿一圈跟最近的实心像素走。"""
    idx = nd.distance_transform_edt(~fg, return_distances=False, return_indices=True)
    return char[idx[0], idx[1]] & (alpha > 0)


def build_scene(name: str, fix_map: dict, standing_w: float) -> tuple[dict, Image.Image, Image.Image]:
    """(元数据, 去白底 RGBA 图, 角色遮罩 L 图)；都已缩放到站姿 rig 比例并裁到内容包围盒。"""
    cfg = fix_map[name]
    rgb, fg, ids, line, blocks, char = analyse(name, fix_map)
    alpha = vx.remove_white_bg(rgb)[..., 3]
    rgba = clean_rgba(rgb, alpha, fg)
    owner = owner_mask(fg, char, alpha)
    ys, xs = np.nonzero(alpha > 0)
    x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    image = Image.fromarray(rgba[y0:y1, x0:x1])
    mask = Image.fromarray((owner[y0:y1, x0:x1] * 255).astype(np.uint8))
    hx0, hy0, hx1, hy1 = cfg["head_box"]
    measured = (hx1 - hx0) / standing_w
    head_scale = float(cfg.get("head_scale", round(measured, 3)))
    k = 1.0 / head_scale
    size = (max(1, round(image.width * k)), max(1, round(image.height * k)))
    if size != image.size:
        image = image.resize(size, Image.Resampling.LANCZOS)
        mask = mask.resize(size, Image.Resampling.LANCZOS)
    a = np.asarray(image)[..., 3]
    char_rs = (np.asarray(mask) > 127) & (a >= CHAR_MIN_ALPHA)
    mask = Image.fromarray((char_rs * 255).astype(np.uint8))

    def point(p):
        return [round((p[0] - x0) * k, 1), round((p[1] - y0) * k, 1)]

    def ellipse(e):
        return [round((e[0] - x0) * k, 1), round((e[1] - y0) * k, 1), round(e[2] * k, 1), round(e[3] * k, 1)]

    cy, cx = np.nonzero(char_rs)
    visible = a >= CHAR_MIN_ALPHA
    # 家具像素 = 可见且离角色超过 FURNITURE_GAP 像素；角色边缘一圈抗锯齿不算（collapse 没有家具，应为 0）
    furniture_px = int((visible & ~nd.binary_dilation(char_rs, iterations=FURNITURE_GAP)).sum())
    info = {
        "file": f"{name}.png", "mask": f"{name}_char.png",
        "size": list(size), "anchor_x": round(size[0] / 2, 1), "ground_y": float(size[1]),
        "char_box": [int(cx.min()), int(cy.min()), int(cx.max()) + 1, int(cy.max()) + 1],
        "head_scale": head_scale, "head_scale_measured": round(measured, 3),
        "head_box": [round((hx0 - x0) * k, 1), round((hy0 - y0) * k, 1),
                     round((hx1 - x0) * k, 1), round((hy1 - y0) * k, 1)],
        "head_top": point(cfg["head_top"]), "mouth": point(cfg["mouth"]),
        "zones": {key: [ellipse(e) for e in value] for key, value in cfg["zones"].items()},
        "breath_gain": float(cfg.get("breath_gain", 1.0)),
        "char_pixels": int(char_rs.sum()), "furniture_pixels": furniture_px,
        "source": SOURCES[name], "source_sha256": source_hash(name), "source_size": [rgb.shape[1], rgb.shape[0]],
        "source_crop": [x0, y0, x1, y1],
    }
    if "z_anchor" in cfg:
        info["z_anchor"] = point(cfg["z_anchor"])
    return info, image, mask


def cmd_build(names) -> None:
    fix_map = load_map()
    standing = standing_head_box()
    standing_w = standing[2] - standing[0]
    SCENES_DIR.mkdir(parents=True, exist_ok=True)
    scenes = {}
    for name in names or SOURCES:
        info, image, mask = build_scene(name, fix_map, standing_w)
        image.save(SCENES_DIR / info["file"], optimize=True)
        mask.save(SCENES_DIR / info["mask"], optimize=True)
        scenes[name] = info
        print(f"{name}: {info['size']}，头部比例 {info['head_scale']}（量得 {info['head_scale_measured']}），"
              f"角色 {info['char_pixels']} px，家具 {info['furniture_pixels']} px")
    data = {"version": 1, "states": {n: n for n in scenes}, "standing_head_width": standing_w, "scenes": scenes}
    SCENES_JSON.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- 对比图与数字（第 1b 步）

def window_extra(info: dict, visible: tuple, foot_x: float) -> dict:
    """各档高度下，scene 比站姿窗口多出的逻辑像素宽度（站姿窗口半宽见 shion/v3_window.py _apply_scale）。"""
    standing_half = max(foot_x - visible[0], visible[2] - foot_x) + SIDE_PADDING
    cx0, _, cx1, _ = info["char_box"]
    scene_half = max(info["anchor_x"] - cx0, cx1 - info["anchor_x"]) + SCENE_MARGIN
    out = {}
    for height in WINDOW_HEIGHTS:
        s = height * V2_VISIBLE_RATIO / (visible[3] - visible[1])
        out[str(height)] = {"standing": int(np.ceil(2 * standing_half * s)),
                            "scene": int(np.ceil(2 * max(standing_half, scene_half) * s))}
        out[str(height)]["extra"] = out[str(height)]["scene"] - out[str(height)]["standing"]
    return out


def cross(draw: ImageDraw.ImageDraw, p, colour, r=14) -> None:
    draw.line([(p[0] - r, p[1]), (p[0] + r, p[1])], fill=colour, width=3)
    draw.line([(p[0], p[1] - r), (p[0], p[1] + r)], fill=colour, width=3)


def zones_image(name: str, info: dict, scale: float) -> Image.Image:
    image = Image.open(SCENES_DIR / info["file"]).convert("RGBA")
    mask = np.asarray(Image.open(SCENES_DIR / info["mask"]))
    gray = Image.new("RGBA", image.size, (130, 135, 145, 255))
    gray.alpha_composite(image)
    a = np.asarray(gray).copy()
    edge = (mask > 127) & ~nd.binary_erosion(mask > 127, iterations=2)
    a[edge] = (0, 255, 255, 255)
    out = Image.fromarray(a)
    overlay = Image.new("RGBA", out.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for cx, cy, rx, ry in info["zones"]["cheek"]:
        d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=(255, 230, 0, 90), outline=(255, 230, 0, 255), width=4)
    for cx, cy, rx, ry in info["zones"]["crown"]:
        d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=(0, 255, 0, 70), outline=(0, 200, 0, 255), width=4)
    hx0, hy0, hx1, hy1 = info["head_box"]
    d.rectangle([hx0, hy0, hx1, hy1], outline=(255, 0, 255, 255), width=3)
    cross(d, info["head_top"], (255, 0, 0, 255))
    cross(d, info["mouth"], (255, 255, 255, 255))
    if "z_anchor" in info:
        cross(d, info["z_anchor"], (255, 120, 0, 255), 20)
    ax, gy = info["anchor_x"], info["ground_y"]
    d.line([(ax, 0), (ax, gy)], fill=(0, 0, 255, 160), width=2)
    d.line([(0, gy - 1), (out.width, gy - 1)], fill=(0, 0, 255, 160), width=2)
    out.alpha_composite(overlay)
    return out.convert("RGB").resize((round(out.width * scale), round(out.height * scale)), Image.Resampling.LANCZOS)


def cmd_check() -> None:
    from v3proto.render import Rig
    data = json.loads(SCENES_JSON.read_text(encoding="utf-8"))
    rig = Rig()
    standing = np.asarray(rig.rest("neutral"))
    ys, xs = np.nonzero(standing[..., 3])
    visible = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    foot_x = float((rig.pivots["hip_l"][0] + rig.pivots["hip_r"][0]) / 2)
    sh = standing_head_box()
    BUILD.mkdir(parents=True, exist_ok=True)
    report = {"standing": {"visible": list(visible), "head_box": list(sh), "foot_x": foot_x}, "scenes": {}}
    # 并排：同一比例、同一地面线（站姿的脚底 = 可见区域底边）
    items = [("standing", Image.fromarray(standing).crop(visible), (sh[0] - visible[0], sh[1] - visible[1], sh[2] - visible[0], sh[3] - visible[1]))]
    for name, info in data["scenes"].items():
        items.append((name, Image.open(SCENES_DIR / info["file"]).convert("RGBA"), tuple(info["head_box"])))
        window = window_extra(info, visible, foot_x)
        report["scenes"][name] = {
            "size": info["size"], "head_scale": info["head_scale"], "head_scale_measured": info["head_scale_measured"],
            "head_width_vs_standing": round((info["head_box"][2] - info["head_box"][0]) / (sh[2] - sh[0]), 3),
            "char_pixels": info["char_pixels"], "furniture_pixels": info["furniture_pixels"],
            "window_width_logical": window}
    height = max(im.height for _, im, _ in items)
    width = sum(im.width for _, im, _ in items) + 40 * (len(items) + 1)
    sheet = Image.new("RGB", (width, height + 60), (130, 135, 145))
    d = ImageDraw.Draw(sheet)
    x = 40
    for label, im, box in items:
        sheet.paste(im, (x, height - im.height + 60), im)
        top = height - im.height + 60
        d.rectangle([x + box[0], top + box[1], x + box[2], top + box[3]], outline=(255, 0, 255), width=4)
        d.text((x, 10), label, fill=(255, 255, 255), font=vx._font(40))
        x += im.width + 40
    d.line([(0, height + 59), (width, height + 59)], fill=(0, 0, 255), width=3)
    scale = min(1.0, 1600 / width)
    sheet.resize((round(width * scale), round((height + 60) * scale)), Image.Resampling.LANCZOS).save(BUILD / "scale-compare.png")
    for name, info in data["scenes"].items():
        zones_image(name, info, min(1.0, OVERVIEW_MAX / max(info["size"]))).save(BUILD / f"zones-{name}.png")
    (BUILD / "scene-build.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    for name, r in report["scenes"].items():
        print(f"{name}: {r['size']} 头部/站姿 {r['head_width_vs_standing']} 角色 {r['char_pixels']} 家具 {r['furniture_pixels']}")
        print("  窗口宽度（逻辑像素，站姿→scene）：",
              {h: f"{w['standing']}→{w['scene']} (+{w['extra']})" for h, w in r["window_width_logical"].items()})


# ---------------------------------------------------------------- 离屏窗口截图（第 3 步）

PREVIEW_HEIGHTS = (160, 200, 260, 320)
PREVIEW_STATES = ("collapse", "bed", "desk")
GRAY = (130, 135, 145)


def _step(w, t, seconds: float) -> None:
    end = t[0] + seconds
    while t[0] < end:
        t[0] += w._timer.interval() / 1000
        w.advance_to(t[0])


def _window(height: int, dpr: float):
    from PySide6.QtCore import Qt
    from shion.v3_window import V3PetWindow
    t = [100.0]
    w = V3PetWindow(height=height, clock=lambda: t[0], autostart=False, debug=False, pixel_ratio=dpr)
    w.setAttribute(Qt.WA_DontShowOnScreen)
    w.auto_side = False
    w.move(300, 120)
    w.show()
    return w, t


def _destroy(w) -> None:
    from PySide6.QtCore import QCoreApplication, QEvent
    w.close()
    w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def _frame_pil(w, scale: int, clip: bool = True):
    from v3proto.render import to_pil
    return to_pil(w.render_scene_frame(scale, clip=clip))


def _on_gray(image: Image.Image) -> Image.Image:
    base = Image.new("RGBA", image.size, GRAY + (255,))
    base.alpha_composite(image.convert("RGBA"))
    return base.convert("RGB")


def _label_font(size: int):
    """带中文的字体（总览图标题用）；找不到就退回 vx._font。"""
    from PIL import ImageFont
    for name in ("msyh.ttc", "simhei.ttf", "simsun.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return vx._font(size)


def _grid(cells, label_h: int = 26) -> Image.Image:
    """cells[行][列] = (标题, 图)。同一行底边对齐。"""
    font = _label_font(18)
    pad = 16
    row_h = [max(im.height for _, im in row) + label_h for row in cells]
    width = max(sum(im.width + pad for _, im in row) + pad for row in cells)
    sheet = Image.new("RGB", (width, sum(row_h) + pad * (len(cells) + 1)), GRAY)
    d = ImageDraw.Draw(sheet)
    y = pad
    for row, h in zip(cells, row_h):
        x = pad
        for title, im in row:
            d.text((x, y), title, fill=(255, 255, 255), font=font)
            sheet.paste(im, (x, y + h - im.height))
            x += im.width + pad
        y += h + pad
    return sheet


def _mask_panel(w, scale: int) -> Image.Image:
    """画面（不裁剪）+ 遮罩轮廓；再并排一张按遮罩裁剪后的样子。"""
    from PySide6.QtGui import QColor, QPainter, QPainterPath
    from v3proto.render import to_pil
    overlay = w._v3_scene_overlay
    shown = overlay is not None and overlay.isVisible()
    left = min(0, overlay.x() - w.x()) if shown else 0
    top = min(0, overlay.y() - w.y()) if shown else 0
    image = w.render_scene_frame(scale, clip=False)
    p = QPainter(image)
    p.translate(-left, -top)                # 图像已带 devicePixelRatio=scale，坐标直接用逻辑像素
    path = QPainterPath()
    path.addRegion(w._v3_region)
    p.fillPath(path, QColor(0, 255, 255, 110))     # 遮罩区域：半透明青色（点得到的地方）
    p.end()
    return _grid([[("遮罩区域（青色 = 点得到）", _on_gray(to_pil(image))),
                   ("按遮罩裁剪后（家具只在覆盖窗里）", _on_gray(_frame_pil(w, scale, clip=True)))]])


def _far_furniture_inside_mask(w, scene) -> dict:
    """离角色远的家具像素有多少落在诗音窗口遮罩里（应为 0：点得穿）。"""
    from PySide6.QtCore import QPoint
    from shion.v3_scene_view import local_origin
    a = vsrt.load_arrays(scene, w.v3_texture_scale)
    reach = max(8, round(44 * a["scale"]))
    far = (a["furniture"][..., 3] >= 250) & ~nd.binary_dilation(a["alpha"] > 0, iterations=reach)
    ys, xs = np.nonzero(far)
    o = local_origin(w, scene, w._v3_scale, 0.0)
    region = w.mask()
    points = list(zip(xs[::40], ys[::40]))
    inside = sum(region.contains(QPoint(round(o.x() + (x / a["scale"] - a["pad"]) * w._v3_scale),
                                        round(o.y() + (y / a["scale"] - a["pad"]) * w._v3_scale)))
                 for x, y in points)
    return {"checked": len(points), "inside": int(inside)}


def cmd_preview() -> None:
    import os
    import statistics
    import time
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from shion.v3_window import V3PetWindow
    V3PetWindow._v3_scene_prewarm = lambda self: None            # 量“用到才同步载入”的耗时
    BUILD.mkdir(parents=True, exist_ok=True)
    report: dict = {"windows": {}, "sync_load_ms": {}, "scene_paint_ms": {}, "furniture_points_inside_mask": {}}
    for dpr, name in ((1.0, "scenes-dpr1.png"), (1.5, "scenes-dpr1.5.png")):
        scale = 2 if dpr > 1 else 1
        rows = []
        for height in PREVIEW_HEIGHTS:
            w, t = _window(height, dpr)
            w.set_state("idle", animate=False)
            _step(w, t, 0.3)
            standing = w.width()
            feet = w.x() + w.width() / 2
            row = []
            for state in PREVIEW_STATES:
                w.set_state(state, animate=False)
                _step(w, t, 0.8)
                row.append((f"{state} {height}px", _on_gray(_frame_pil(w, scale))))
                info = report["windows"].setdefault(f"{height}@{dpr}", {"standing": standing})
                info[state] = {"width": w.width(), "extra": w.width() - standing,
                               "feet_moved": round(abs((w.x() + w.width() / 2) - feet), 2)}
                if dpr == 1.5 or height == 260:
                    pet = QImage(w.size() * scale, QImage.Format_ARGB32_Premultiplied)
                    pet.setDevicePixelRatio(scale)
                    times = []
                    for _ in range(20):
                        pet.fill(0)
                        q = QPainter(pet)
                        t0 = time.perf_counter()
                        w._draw_sprite(q, w._frame)
                        times.append((time.perf_counter() - t0) * 1000)
                        q.end()
                    report["scene_paint_ms"][f"{state}@{height}x{dpr}"] = round(statistics.median(times), 2)
                _step(w, t, 0.1)
                w.set_state("idle", animate=False)
                _step(w, t, 0.5)
            report["sync_load_ms"][f"{height}@{dpr}"] = dict(zip(PREVIEW_STATES, w._v3_scene_load_ms))
            rows.append(row)
            _destroy(w)
        _grid(rows).save(BUILD / name)
    # 260 高：切换四帧（直接切 + 小弹跳）、遮罩轮廓、敲头最深帧
    for state in PREVIEW_STATES:
        w, t = _window(260, 1.0)
        w.set_state("idle", animate=False)
        _step(w, t, 0.3)
        w.set_state(state, animate=False)
        frames = []
        elapsed = 0.0
        for target in (0.0, 0.08, 0.16, 0.24):
            _step(w, t, target - elapsed)
            elapsed = target
            frames.append((f"t={target:.2f}s sy={w._v3_scene_affine[0]:.3f}", _on_gray(_frame_pil(w, 1))))
        _grid([frames]).save(BUILD / f"switch-{state}.png")
        _step(w, t, 0.6)
        _mask_panel(w, 2).save(BUILD / f"mask-{state}.png")
        if state != "collapse":
            report["furniture_points_inside_mask"][state] = _far_furniture_inside_mask(w, w._v3_scenes[state])
        rest = _on_gray(_frame_pil(w, 2))
        w._v3_scene_override = (0.96, 0.0)                 # 敲头 + 点击压扁的最深：整图缩回约 4%
        w._v3_mask_force = True
        w._refresh(w._clock())
        w._update_mask(w._clock())
        pressed = _on_gray(_frame_pil(w, 2))
        _grid([[("静止", rest), ("敲头最深 sy=0.96", pressed)]]).save(BUILD / f"knock-{state}.png")
        _destroy(w)
    app.processEvents()
    (BUILD / "preview.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=1, ensure_ascii=False))


def main(argv=None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(__doc__)
        return
    cmd, rest = args[0], args[1:]
    if cmd == "regions":
        cmd_regions(rest)
    elif cmd == "build":
        cmd_build(rest)
    elif cmd == "check":
        cmd_check()
    elif cmd == "preview":
        cmd_preview()
    else:
        raise SystemExit(f"未知子命令：{cmd}")


if __name__ == "__main__":
    main()
