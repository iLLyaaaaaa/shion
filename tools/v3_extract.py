"""V3 立绘第 0 步：把零件图切成独立零件，并以 ref.png 为准对位。

素材在 assets/sprites/raw/v3/：
- ref.png             定稿总图（白底 RGB，得意脸）
- face_sheet.png      表情零件
- body_sheet.png      后发/身体/手臂/腿/花饰/呆毛
- hair_head_sheet.png 前刘海/左右鬓发/头部底色

用法：
  python tools/v3_extract.py extract   切连通块，生成带编号的总览图 build/v3/overview_*.png
  python tools/v3_extract.py name      按 assets/sprites/v3/parts_map.json 输出零件 PNG
  python tools/v3_extract.py rig       以 ref.png 为准对位：匹配缓存 build/v3/places.json
                                       （tools/v3_slice.py 用它放种子和垫底），第一版 rig 写 build/v3/rig_v1.json
  python tools/v3_extract.py compose   第一版：拼中性脸/得意脸并和 ref 对比（build/v3/，已弃用）
  python tools/v3_extract.py all       name + rig + compose

2026-11-05 起正式方案改为 tools/v3_slice.py（可见部分直接从 ref 切，表情用差分图），
本脚本只负责切 GPT 零件图和对位；GPT 零件现在只用作垫底和分区种子。

坐标约定：rig.json 里的坐标都是 ref.png 的像素坐标（1086×1448）。每个零件先按 scale 缩放、
再绕自身中心旋转 rot 度（逆时针为正，与 PIL 的 rotate 一致），中心放在 (cx, cy)。
左右一律指画面左/右。
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from scipy import ndimage as nd
from scipy.signal import fftconvolve

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "assets" / "sprites" / "raw" / "v3"
OUT = ROOT / "assets" / "sprites" / "v3"
PARTS = OUT / "parts"
MAP_FILE = OUT / "parts_map.json"
RIG_FILE = OUT / "rig.json"        # V3 正式 rig（v2，ref 切片），由 tools/v3_slice.py 写
BUILD = ROOT / "build" / "v3"
RIG_V1_FILE = BUILD / "rig_v1.json"  # 第一版，仅作垫底和种子的对位参考

HALO_ALPHA = 16      # 低于这个 alpha 的像素算光晕，直接去掉
SOLID_ALPHA = 235    # 高于这个 alpha 的算完全不透明
MIN_AREA = 200       # 小于这个面积的连通块当碎屑丢掉
SHEETS = {"F": "face_sheet", "B": "body_sheet", "H": "hair_head_sheet"}
WHITE_BG = 245       # ref.png：min(RGB) 不低于这个值且和边缘连通的算白底
VISIBLE_SCORE = 0.25 # NCC 分数低于这个值视为“看不见”。零件图与 ref 不是逐像素一致的（如花饰飘带），分数整体偏低
CHEEK_FEATHER = 10   # 鼓脸颊切口的羽化宽度（零件原图像素）

# 图层顺序（从下到上）。表情槽位一次只显示一个变体。
#（2026-11-05 用户调整：腮红移到鬓发和鼓脸颊之上，保证两侧腮红都看得见）
LAYERS = ["back_hair", "leg_l", "leg_r", "body", "arm_l", "arm_r", "head_base",
          "eye_l", "eye_r", "mouth", "brow_l", "brow_r",
          "side_hair_l", "cheek_puff_l", "side_hair_r", "cheek_puff_r",
          "blush_l", "blush_r", "bangs", "flower", "ahoge"]
EXPR_SLOTS = {
    "eye": ["open", "happy_closed", "half", "wide", "dizzy", "teary"],
    "mouth": ["smile", "open_small", "open_big", "cat", "pout", "wavy"],
    "brow": ["normal", "angry", "worried", "smug"],
    "blush": ["normal", "strong"],
}
PARENTS = {"body": None, "leg_l": "body", "leg_r": "body", "arm_l": "body", "arm_r": "body",
           "head_base": "body", "back_hair": "head_base", "bangs": "head_base",
           "side_hair_l": "head_base", "side_hair_r": "head_base", "flower": "head_base",
           "ahoge": "head_base", "cheek_puff_l": "head_base", "head_base_alt": None}
ROTATABLE = {"arm_l", "arm_r", "leg_l", "leg_r", "side_hair_l", "side_hair_r", "ahoge", "flower"}
REF_FACE = {"eye": "half", "mouth": "cat"}   # ref.png 是得意脸（用户给定）
SLOT_VISIBLE = {"brow": 0.5, "blush": 0.4}   # 眉毛是细线，容易配到别的线上，门槛要高一些
FACES = {
    "neutral": {"eye": "open", "mouth": "smile", "brow": "normal", "blush": "normal"},
    "smug": {"eye": "half", "mouth": "cat"},   # 眉和腮红用 ref 里匹配到的那套
}


# ---------------------------------------------------------------- 切零件

def clean_alpha(rgba: np.ndarray) -> np.ndarray:
    """去光晕：alpha<HALO_ALPHA 置 0；半透明边缘的颜色换成最近不透明像素的颜色（去白边）。"""
    a = rgba.copy()
    al = a[..., 3]
    al[al < HALO_ALPHA] = 0
    al[al >= SOLID_ALPHA] = 255
    opaque = al == 255
    semi = (al > 0) & ~opaque
    if semi.any() and opaque.any():
        _, (iy, ix) = nd.distance_transform_edt(~opaque, return_indices=True)
        a[semi, :3] = a[iy[semi], ix[semi], :3]
    a[al == 0, :3] = 0
    return a


def label_sheet(rgba: np.ndarray) -> np.ndarray:
    labels, _ = nd.label(rgba[..., 3] > 0, structure=np.ones((3, 3)))
    return labels


def find_components(rgba: np.ndarray, prefix: str) -> list[dict]:
    """按 alpha 连通区域切块。编号按“行从上到下、行内从左到右”，重跑时稳定。"""
    labels = label_sheet(rgba)
    objs = nd.find_objects(labels)
    areas = np.bincount(labels.ravel())
    comps = []
    for i, sl in enumerate(objs, start=1):
        if sl is None or areas[i] < MIN_AREA:
            continue
        y0, y1 = sl[0].start, sl[0].stop
        x0, x1 = sl[1].start, sl[1].stop
        comps.append({"label": i, "bbox": [x0, y0, x1, y1], "area": int(areas[i]),
                      "cy": (y0 + y1) / 2, "cx": (x0 + x1) / 2, "h": y1 - y0})
    if not comps:
        return []
    comps.sort(key=lambda c: c["cy"])
    tol = float(np.median([c["h"] for c in comps])) * 0.5
    rows, row_start = [[]], comps[0]["cy"]
    for c in comps:
        if c["cy"] - row_start > tol:
            rows.append([])
            row_start = c["cy"]
        rows[-1].append(c)
    ordered = [c for row in rows for c in sorted(row, key=lambda c: c["cx"])]
    for n, c in enumerate(ordered, start=1):
        c["id"] = f"{prefix}{n:02d}"
    return ordered


def merge_components(rgba: np.ndarray, labels: np.ndarray, comps: list[dict]) -> tuple[Image.Image, list[int]]:
    """把若干连通块合成一张紧贴外框的透明图，返回 (图, 在原图里的外框)。"""
    x0 = min(c["bbox"][0] for c in comps)
    y0 = min(c["bbox"][1] for c in comps)
    x1 = max(c["bbox"][2] for c in comps)
    y1 = max(c["bbox"][3] for c in comps)
    crop = rgba[y0:y1, x0:x1].copy()
    keep = np.isin(labels[y0:y1, x0:x1], [c["label"] for c in comps])
    crop[~keep] = 0
    return Image.fromarray(crop), [x0, y0, x1, y1]


def load_sheet(name: str) -> np.ndarray:
    return clean_alpha(np.array(Image.open(RAW / f"{name}.png").convert("RGBA")))


def _font(size: int):
    for f in ("arialbd.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            pass
    return ImageFont.load_default()


def checker(size: tuple[int, int], cell: int = 24) -> Image.Image:
    w, h = size
    yy, xx = np.mgrid[0:h, 0:w]
    v = np.where(((yy // cell) + (xx // cell)) % 2 == 0, 200, 170).astype(np.uint8)
    return Image.fromarray(np.dstack([v, v, v, np.full_like(v, 255)]))


def overview(rgba: np.ndarray, comps: list[dict], max_side: int = 1400) -> Image.Image:
    h, w = rgba.shape[:2]
    img = checker((w, h))
    img.alpha_composite(Image.fromarray(rgba))
    d = ImageDraw.Draw(img)
    font = _font(max(28, w // 40))
    for c in comps:
        x0, y0, x1, y1 = c["bbox"]
        d.rectangle([x0, y0, x1 - 1, y1 - 1], outline=(230, 20, 60, 255), width=3)
        tx, ty = x0 + 4, max(0, y0 - font.size - 6) if y0 > font.size + 6 else y0 + 4
        tb = d.textbbox((tx, ty), c["id"], font=font)
        d.rectangle([tb[0] - 3, tb[1] - 3, tb[2] + 3, tb[3] + 3], fill=(255, 255, 255, 230))
        d.text((tx, ty), c["id"], fill=(200, 0, 40, 255), font=font)
    s = min(1.0, max_side / max(w, h))
    if s < 1:
        img = img.resize((round(w * s), round(h * s)), Image.LANCZOS)
    return img


def read_map(path: Path = MAP_FILE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_map(mapping: dict) -> dict[str, list[str]]:
    """零件名 → 块编号列表；null 的零件丢掉。同一块不能分给两个零件。"""
    out, used = {}, {}
    for name, ids in mapping["parts"].items():
        if ids is None:
            continue
        ids = [ids] if isinstance(ids, str) else list(ids)
        for i in ids:
            if i in used:
                raise ValueError(f"块 {i} 同时分给了 {used[i]} 和 {name}")
            used[i] = name
        out[name] = ids
    return out


def save_png(img: Image.Image, path: Path, tries: int = 5) -> None:
    """文件偶尔会被杀毒软件/同步盘短暂占用，失败就稍等重试。"""
    import time
    path.parent.mkdir(parents=True, exist_ok=True)
    for i in range(tries):
        try:
            img.save(path, optimize=True)
            return
        except OSError:
            if i == tries - 1:
                raise
            time.sleep(0.5)


def cmd_extract() -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    table = {}
    for prefix, name in SHEETS.items():
        rgba = load_sheet(name)
        comps = find_components(rgba, prefix)
        overview(rgba, comps).convert("RGB").save(BUILD / f"overview_{name.split('_')[0]}.png")
        for c in comps:
            table[c["id"]] = {"sheet": name, "bbox": c["bbox"], "area": c["area"]}
        print(f"{name}: {len(comps)} blocks")
    (BUILD / "components.json").write_text(json.dumps(table, indent=1), encoding="utf-8")


def cmd_name() -> dict:
    parts = resolve_map(read_map())
    sheets, comps = {}, {}
    for prefix, name in SHEETS.items():
        rgba = load_sheet(name)
        labels = label_sheet(rgba)
        sheets[prefix] = (rgba, labels)
        for c in find_components(rgba, prefix):
            comps[c["id"]] = c
    sources = {}
    for part, ids in parts.items():
        missing = [i for i in ids if i not in comps]
        if missing:
            raise ValueError(f"{part}: 找不到块 {missing}")
        prefixes = {i[0] for i in ids}
        if len(prefixes) != 1:
            raise ValueError(f"{part}: 块来自不同的零件图 {ids}")
        rgba, labels = sheets[prefixes.pop()]
        img, bbox = merge_components(rgba, labels, [comps[i] for i in ids])
        save_png(img, PARTS / f"{part}.png")
        sources[part] = {"blocks": ids, "sheet": SHEETS[ids[0][0]], "bbox": bbox}
    (OUT / "sources.json").write_text(json.dumps(sources, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(sources)} parts -> {PARTS.relative_to(ROOT)}")
    return sources


# ---------------------------------------------------------------- 图像变换

def transform(img: Image.Image, scale: float, rot: float) -> Image.Image:
    """先缩放再绕中心旋转（逆时针为正）。用预乘 alpha，边缘不发黑。"""
    w, h = img.size
    out = img.convert("RGBa")
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    if (nw, nh) != (w, h):
        out = out.resize((nw, nh), Image.LANCZOS)
    if rot:
        out = out.rotate(rot, resample=Image.BICUBIC, expand=True)
    return out.convert("RGBA")


def local_to_ref(pt, size, place) -> tuple[float, float]:
    """零件原图里的点 (u, v) → ref 坐标。place = {cx, cy, scale, rot}。"""
    w, h = size
    dx, dy = (pt[0] - w / 2) * place["scale"], (pt[1] - h / 2) * place["scale"]
    t = math.radians(place["rot"])
    # 屏幕坐标 y 向下，逆时针旋转 t：
    x = dx * math.cos(t) + dy * math.sin(t)
    y = -dx * math.sin(t) + dy * math.cos(t)
    return place["cx"] + x, place["cy"] + y


def paste_center(canvas: Image.Image, img: Image.Image, cx: float, cy: float) -> None:
    x, y = round(cx - img.width / 2), round(cy - img.height / 2)
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    layer.paste(img, (x, y))
    canvas.alpha_composite(layer)


def render(img: Image.Image, place: dict, size: tuple[int, int]) -> Image.Image:
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    paste_center(layer, transform(img, place["scale"], place["rot"]), place["cx"], place["cy"])
    return layer


# ---------------------------------------------------------------- ref 去白底

def remove_white_bg(rgb: np.ndarray, thr: int = WHITE_BG) -> np.ndarray:
    """只去掉和图像边缘连通的近白像素，人物内部的白色（高光、眼白）保留。返回 RGBA。"""
    white = rgb.min(axis=2) >= thr
    labels, _ = nd.label(white)
    edge = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    bg = np.isin(labels, edge[edge > 0])
    # 紧贴背景的一圈抗锯齿像素按“白度”给半透明
    ring = nd.binary_dilation(bg, iterations=2) & ~bg
    alpha = np.full(white.shape, 255, np.uint8)
    alpha[bg] = 0
    m = rgb[ring].min(axis=1).astype(float)
    alpha[ring] = np.clip((255 - m) / (255 - 180) * 255, 0, 255).astype(np.uint8)
    return np.dstack([rgb, alpha])


# ---------------------------------------------------------------- 模板匹配

def _corr(img: np.ndarray, ker: np.ndarray) -> np.ndarray:
    return fftconvolve(img, ker[::-1, ::-1], mode="valid", axes=(0, 1))


def masked_ncc(I: np.ndarray, W: np.ndarray, T: np.ndarray, M: np.ndarray, min_overlap: float = 0.4):
    """带双遮罩的归一化互相关（Padfield 2012 的写法）。

    I: 图像 HxWx3，W: 图像侧权重 HxW（0 = 已被上层零件盖住，不参与比较）
    T: 模板 hxwx3，M: 模板遮罩 hxw（零件 alpha）
    图像四周先补 hxw 的白边，模板可以有一部分伸出画面。
    返回 (分数图, 补边量)，分数图 [i, j] 对应模板左上角在 (j - pad_x, i - pad_y)。
    """
    h, w = M.shape
    py, px = h - 1, w - 1
    I = np.pad(I, ((py, py), (px, px), (0, 0)), constant_values=1.0)
    W = np.pad(W, ((py, py), (px, px)), constant_values=1.0)
    Wc, Mc = W[..., None], M[..., None]
    A, B = Wc * I, Mc * T
    O = _corr(W, M)
    sI = _corr(A, Mc)
    sI2 = _corr(A * I, Mc)
    sT = _corr(Wc, B)
    sT2 = _corr(Wc, B * T)
    sIT = _corr(A, B)
    Os = np.maximum(O, 1e-6)[..., None]
    num = (sIT - sI * sT / Os).sum(-1)
    vI = (sI2 - sI ** 2 / Os).sum(-1)
    vT = (sT2 - sT ** 2 / Os).sum(-1)
    den = np.sqrt(np.maximum(vI, 1e-9) * np.maximum(vT, 1e-9))
    score = num / den
    score[O < min_overlap * M.sum()] = -1
    score[(vI < 1e-6) | (vT < 1e-6)] = -1
    return score, (py, px)


def _template(img: Image.Image, scale: float, rot: float):
    t = np.asarray(transform(img, scale, rot), dtype=np.float32) / 255.0
    return t[..., :3], (t[..., 3] > 0.5).astype(np.float32)


def _shrink(arr: np.ndarray, f: int) -> np.ndarray:
    if f == 1:
        return arr
    h, w = arr.shape[:2]
    h2, w2 = h // f * f, w // f * f
    a = arr[:h2, :w2]
    return a.reshape(h2 // f, f, w2 // f, f, *a.shape[2:]).mean(axis=(1, 3))


def auto_factor(img: Image.Image, scales) -> int:
    """粗搜的缩小倍数：让缩小后的模板短边约 48 px，最多缩 4 倍（缩 8 倍时花饰会被错配到鞋上）。"""
    side = min(img.size) * float(np.median(scales))
    return int(max(1, min(4, side // 48)))


def match_part(img: Image.Image, I: np.ndarray, W: np.ndarray, *, window=None,
               scales=None, rots=(0.0,), factor: int | None = None, min_overlap: float = 0.4) -> dict:
    """在 I（ref，0..1 浮点）里找零件 img。返回 {cx, cy, scale, rot, score}。

    粗搜：图和模板都缩小 factor 倍，扫 scales×rots；精搜：原分辨率附近细调。
    window = (x0, y0, x1, y1) 限定零件中心的搜索范围（ref 坐标）。
    """
    if scales is None:
        scales = np.geomspace(0.45, 1.6, 33)
    if factor is None:
        factor = auto_factor(img, scales)
    H, Wd = W.shape
    x0, y0, x1, y1 = window or (0, 0, Wd, H)
    best = {"score": -2.0}
    # 粗搜只在 window 外扩一点的范围里做，节省时间
    for s in scales:
        for r in rots:
            T, M = _template(img, s / factor, r)
            th, tw = M.shape
            if th < 4 or tw < 4 or M.sum() < 8:
                continue
            mx0 = max(0, int((x0 - tw * factor / 2) // factor) - 2)
            my0 = max(0, int((y0 - th * factor / 2) // factor) - 2)
            mx1 = min(Wd // factor, int((x1 + tw * factor / 2) // factor) + 2)
            my1 = min(H // factor, int((y1 + th * factor / 2) // factor) + 2)
            Is = I[my0 * factor:my1 * factor, mx0 * factor:mx1 * factor]
            Ws = W[my0 * factor:my1 * factor, mx0 * factor:mx1 * factor]
            Is, Ws = _shrink(Is, factor), (_shrink(Ws, factor) > 0.5).astype(np.float32)
            if Is.shape[0] < 2 or Is.shape[1] < 2:
                continue
            sc, (py, px) = masked_ncc(Is, Ws, T, M, min_overlap)
            # 限定中心在 window 内
            iy, ix = np.mgrid[0:sc.shape[0], 0:sc.shape[1]]
            ccx = (ix - px + tw / 2 + mx0) * factor
            ccy = (iy - py + th / 2 + my0) * factor
            sc = np.where((ccx >= x0) & (ccx < x1) & (ccy >= y0) & (ccy < y1), sc, -2)
            k = int(np.argmax(sc))
            if sc.flat[k] > best["score"]:
                best = {"score": float(sc.flat[k]), "cx": float(ccx.flat[k]), "cy": float(ccy.flat[k]),
                        "scale": float(s), "rot": float(r)}
    if best["score"] <= -2:
        raise ValueError("匹配失败：模板太小或搜索范围为空")
    return refine(img, I, W, best, step=factor, rot_on=len(rots) > 1, min_overlap=min_overlap)


def _crop(arr: np.ndarray, x0: int, y0: int, w: int, h: int, fill: float) -> np.ndarray:
    """从 arr 里取 (x0, y0, w, h) 一块，越界部分用 fill 填。"""
    out = np.full((h, w) + arr.shape[2:], fill, dtype=np.float32)
    H, W = arr.shape[:2]
    sx0, sy0, sx1, sy1 = max(0, x0), max(0, y0), min(W, x0 + w), min(H, y0 + h)
    if sx1 > sx0 and sy1 > sy0:
        out[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = arr[sy0:sy1, sx0:sx1]
    return out


def refine(img: Image.Image, I: np.ndarray, W: np.ndarray, start: dict, *, step: int = 4,
           rot_on: bool = False, min_overlap: float = 0.4) -> dict:
    """在粗结果附近细调缩放、角度和位置：先半分辨率，再原分辨率。"""
    best = dict(start, score=-2.0)   # 粗搜分数是低分辨率下的，不和后面比
    w, h = img.size
    big = w * h * start["scale"] ** 2 > 120_000     # 大零件最后一轮停在半分辨率，误差约 1 px
    mid = max(2, step // 2)
    plan = [(mid, 0.06, 5, (np.arange(-5, 6, 5) if rot_on else [0]), step * 2 + 4),
            (2 if big else 1, 0.015, 5, (np.arange(-2, 2.1, 2) if rot_on else [0]), mid * 2 + 2)]
    if mid == 2 and big:
        plan = plan[:1] + [(2, 0.015, 5, plan[1][3], 4)]
    for f, span, n_s, drot, margin in plan:
        If, Wf = (_shrink(I, f), _shrink(W, f)) if f > 1 else (I, W)
        cur = dict(best)
        best["score"] = -2.0
        for s in cur["scale"] * np.linspace(1 - span, 1 + span, n_s):
            for dr in drot:
                r = float(cur["rot"] + dr)
                T, M = _template(img, s / f, r)
                th, tw = M.shape
                m = max(2, margin // f)
                x0 = int(round(cur["cx"] / f - tw / 2)) - m
                y0 = int(round(cur["cy"] / f - th / 2)) - m
                Is = _crop(If, x0, y0, tw + 2 * m, th + 2 * m, 1.0)
                Ws = _crop(Wf, x0, y0, tw + 2 * m, th + 2 * m, 1.0)
                sc, (py, px) = masked_ncc(Is, Ws, T, M, min_overlap)
                sc = sc[py:py + 2 * m + 1, px:px + 2 * m + 1]   # 只看模板完全在窗口里的位置
                k = int(np.argmax(sc))
                if sc.flat[k] > best["score"]:
                    iy, ix = divmod(k, sc.shape[1])
                    best = {"score": float(sc.flat[k]), "cx": (x0 + ix + tw / 2) * f,
                            "cy": (y0 + iy + th / 2) * f, "scale": float(s), "rot": r}
    return best


# ---------------------------------------------------------------- 对位主流程

def footprint(img: Image.Image, place: dict, size) -> np.ndarray:
    return np.asarray(render(img, place, size))[..., 3] > 128


def _bbox(mask: np.ndarray):
    ys, xs = np.nonzero(mask)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def slot_of(name: str):
    """'eye_half_l' → ('eye', 'half', 'l')；'mouth_cat' → ('mouth', 'cat', '')。不是表情零件返回 None。"""
    head, _, rest = name.partition("_")
    if head not in EXPR_SLOTS:
        return None
    side = ""
    if rest.endswith("_l") or rest.endswith("_r"):
        rest, side = rest[:-2], rest[-1]
    return head, rest, side


def cheek_cut(alpha: np.ndarray) -> dict:
    """在头部底色里找画面左侧的鼓脸颊。

    头部左轮廓从头顶往下先向外扩，到最宽处后往回收，再在脸颊处鼓出来。
    鼓包所在的行 = 下半部分里最左的那一行；回收最深处（鼓包上方 leftmost x 最大的行）作为上切口。
    返回零件原图坐标：{top, bulge_row, bulge_x, indent_x}。
    """
    h, w = alpha.shape
    solid = alpha > 128
    left = np.array([np.argmax(r) if r.any() else w for r in solid])
    rows = np.nonzero(solid.any(axis=1))[0]
    top, bot = rows[0], rows[-1]
    lower = np.arange(top + (bot - top) // 2, bot - (bot - top) // 12)
    bulge_row = int(lower[np.argmin(left[lower])])
    upper = np.arange(top, top + (bot - top) // 2)       # 只在上半部分找头最宽处，避开鼓包本身
    widest = int(upper[np.argmin(left[upper])])
    between = np.arange(widest, bulge_row)
    indent = int(between[np.argmax(left[between])])
    # 鼓包下沿：鼓包以下 leftmost x 回到凹口深度的六成以内为止（再往下是下巴轮廓）
    below = np.arange(bulge_row, bot)
    out = below[left[below] < left[indent] * 0.6]
    bottom = int(out.max()) if len(out) else bulge_row
    return {"top": indent, "bulge_row": bulge_row, "bottom": bottom, "bulge_x": int(left[bulge_row]),
            "indent_x": int(left[indent])}


def make_cheek(head: Image.Image, top: int, cut_x: int, feather: int = CHEEK_FEATHER,
               bottom: int | None = None) -> Image.Image:
    """从头部底色里拷出鼓脸颊：x < cut_x、top < y < bottom 的部分，右、上、下三边的切口羽化。
    头部底色本身保持完整，鼓脸颊作为一层盖在左鬓发上面。
    只取鼓包那几行：带上鼓包上方的头部轮廓会像一缕头发，带上下巴会和头部底色的下巴错开成接缝。"""
    a = np.asarray(head).copy()
    h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    fx = np.clip((cut_x - xx) / feather, 0, 1)
    fy = np.clip((yy - top) / feather, 0, 1)
    if bottom is not None:
        fy = fy * np.clip((bottom - yy) / feather, 0, 1)
    a[..., 3] = (a[..., 3] * fx * fy).astype(np.uint8)
    img = Image.fromarray(a)
    bb = img.getbbox()
    out = img.crop(bb)
    out.info["offset"] = (bb[0], bb[1])
    return out


FULL_SCALES = np.geomspace(0.45, 1.6, 33)


def scale_range(sheet_scale: dict, sheet: str | None):
    """同一张零件图的第一个零件全范围搜；之后只搜它的缩放 ±25%。"""
    if sheet and sheet in sheet_scale:
        return sheet_scale[sheet] * np.geomspace(0.8, 1.25, 11)
    return FULL_SCALES


def build_rig(ref_rgb: np.ndarray, parts: dict[str, Image.Image], sheet_of: dict | None = None,
              log=print) -> dict:
    ref = remove_white_bg(ref_rgb)
    H, Wd = ref.shape[:2]
    I = ref_rgb.astype(np.float32) / 255.0
    W = np.ones((H, Wd), np.float32)
    places: dict[str, dict] = {}
    sheet_of = sheet_of or {}
    sheet_scale: dict[str, float] = {}

    def place(name, **kw):
        sh = sheet_of.get(name)
        kw.setdefault("scales", scale_range(sheet_scale, sh))
        t0 = time.time()
        res = match_part(parts[name], I, W, **kw)
        if sh and res["score"] >= VISIBLE_SCORE:
            sheet_scale.setdefault(sh, res["scale"])
        res["method"] = "match"
        places[name] = res
        log(f"  {name:22s} t={time.time() - t0:4.0f}s score={res['score']:.3f} scale={res['scale']:.3f} rot={res['rot']:+.1f} "
            f"c=({res['cx']:.0f},{res['cy']:.0f})")
        return res

    def cover(name):
        W[footprint(parts[name], places[name], (Wd, H))] = 0

    sil = ref[..., 3] > 128
    fx0, fy0, fx1, fy1 = _bbox(sil)
    full = (fx0, fy0, fx1, fy1)

    # 1) 从最上层往下：先放完全露出来的零件，再把它们盖住的地方从比较里去掉
    for n in ["flower", "ahoge", "bangs", "side_hair_r", "side_hair_l"]:
        place(n, window=full, rots=(-20.0, -10.0, 0.0, 10.0, 20.0) if n in ROTATABLE else (0.0,))
        cover(n)

    # 2) 表情：在刘海和鬓发围出的脸部范围里搜
    # 脸 = 两侧鬓发中线之间、刘海中部往下；全用刘海+鬓发外框会把鬓发里的橙色发丝当成眼睛
    bb, bl, br = (_bbox(footprint(parts[n], places[n], (Wd, H))) for n in ("bangs", "side_hair_l", "side_hair_r"))
    face_win = ((bl[0] + bl[2]) // 2, (bb[1] + bb[3]) // 2, (br[0] + br[2]) // 2,
                bb[3] + (bb[3] - bb[1]) // 2)
    mid_x = (face_win[0] + face_win[2]) // 2
    log(f"  face window {face_win}")
    # 2a) ref 是得意脸（已知）：先放半眯眼和猫嘴，定出表情图的缩放。
    #     只靠分数挑眼型/嘴型不可靠（普通睁眼和半眯眼分数打平，小张嘴比猫嘴还高）。
    chosen = dict(REF_FACE)
    known = [f"eye_{REF_FACE['eye']}_l", f"eye_{REF_FACE['eye']}_r", f"mouth_{REF_FACE['mouth']}"]
    # 先两只眼（左眼只在左半边找、右眼只在右半边），表情零件应当基本露在外面
    for n, win in ((known[0], (face_win[0], face_win[1], mid_x, face_win[3])),
                   (known[1], (mid_x, face_win[1], face_win[2], face_win[3]))):
        place(n, window=win, factor=2, min_overlap=0.7)
    fscale = float(np.mean([places[n]["scale"] for n in known[:2]]))
    near = fscale * np.geomspace(0.92, 1.08, 5)
    log(f"  face scale {fscale:.3f}")
    # 嘴：两眼之间、眼睛下方，缩放跟眼睛一致（否则会配到领巾上）
    el = _bbox(footprint(parts[known[0]], places[known[0]], (Wd, H)))
    er = _bbox(footprint(parts[known[1]], places[known[1]], (Wd, H)))
    eh = max(el[3] - el[1], er[3] - er[1])
    mouth_win = ((el[0] + el[2]) // 2, max(el[3], er[3]), (er[0] + er[2]) // 2, max(el[3], er[3]) + eh * 3)
    place(known[2], window=mouth_win, scales=near, factor=1, min_overlap=0.7)
    # 2b) 眉毛和腮红：缩放限定在表情图缩放附近，位置限定在对应眼睛的上方/下方，再挑分数最高的一款
    eye_box = {s: _bbox(footprint(parts[f"eye_{REF_FACE['eye']}_{s}"], places[f"eye_{REF_FACE['eye']}_{s}"], (Wd, H)))
               for s in ("l", "r")}
    for n in known:
        cover(n)
    mid = (places[known[0]]["cx"] + places[known[1]]["cx"]) / 2     # 脸部中线（两眼中点）
    for slot in ("brow", "blush"):
        results = {}
        for var in EXPR_SLOTS[slot]:
            for s in ("l", "r"):
                n = f"{slot}_{var}_{s}"
                if n not in parts:
                    continue
                x0, y0, x1, y1 = eye_box[s]
                ew, eh = x1 - x0, y1 - y0
                if slot == "brow":   # 只在眼睛上沿以上找，否则会把眼线当成眉毛
                    win = (x0 - ew * 0.3, y0 - eh * 2.5, x1 + ew * 0.3, y0 - eh * 0.2)
                else:                # 只在眼睛外侧往下找，否则会把嘴当成腮红
                    cx_e = (x0 + x1) / 2
                    win = ((x0 - ew * 0.8, (y0 + y1) / 2, cx_e, y1 + eh * 2.5) if s == "l"
                           else (cx_e, (y0 + y1) / 2, x1 + ew * 0.8, y1 + eh * 2.5))
                r = match_part(parts[n], I, W, window=tuple(map(int, win)), scales=near, factor=1)
                results[n] = r
                log(f"    {n:22s} score={r['score']:.3f} scale={r['scale']:.3f} c=({r['cx']:.0f},{r['cy']:.0f})")
        # 一侧可能被头发挡住，所以按“较好那一侧”的分数挑款式
        thr = SLOT_VISIBLE[slot]
        ranking = sorted(((max(r["score"] for n, r in results.items() if slot_of(n)[1] == v), v)
                          for v in {slot_of(n)[1] for n in results}), reverse=True)
        log(f"  {slot}: " + "  ".join(f"{v}={sc:.3f}" for sc, v in ranking) + f"  (threshold {thr})")
        best_score, best_var = ranking[0]
        chosen[slot] = best_var if best_score >= thr else None
        if not chosen[slot]:
            continue
        nl, nr = f"{slot}_{best_var}_l", f"{slot}_{best_var}_r"
        rl, rr = results[nl], results[nr]
        good, bad = (nl, nr) if rl["score"] >= rr["score"] else (nr, nl)
        rg, rb = results[good], results[bad]
        places[good] = dict(rg, method="match")
        if rb["score"] >= thr and abs(rb["scale"] / rg["scale"] - 1) <= 0.1:
            places[bad] = dict(rb, method="match")
        else:   # 另一侧不可靠：按脸部中线镜像
            places[bad] = {"cx": 2 * mid - rg["cx"], "cy": rg["cy"], "scale": rg["scale"], "rot": -rg["rot"],
                           "score": rb["score"], "method": "inferred", "from": f"mirror of {good}"}
            log(f"  {bad} mirrored from {good}")
        if slot == "brow":
            cover(nl)
            cover(nr)

    # 3) 头部底色：只用没被头发和五官盖住的皮肤比较。露出来的皮肤很少，全图搜会被零星没盖住的
    #    小块带偏，所以中心限定在刘海中线附近、刘海中部到刘海下沿往下半个刘海高的范围里
    bw_, bh_ = bb[2] - bb[0], bb[3] - bb[1]
    bcx = (bb[0] + bb[2]) / 2
    head_win = (int(bcx - bw_ * 0.15), int(bb[1] + bh_ * 0.4), int(bcx + bw_ * 0.15), int(bb[3] + bh_ * 0.5))
    place("head_base", window=head_win, factor=2)
    cover("head_base")
    # 4) 手臂 → 身体 → 腿 → 后发
    for n in ["arm_l", "arm_r", "body", "leg_l", "leg_r"]:
        place(n, window=full, rots=(-20.0, -10.0, 0.0, 10.0, 20.0) if n in ROTATABLE else (0.0,))
        cover(n)
    # 5) 后发几乎全被挡住，全图搜会跑偏：缩放取身体那张图已匹配零件的中位数，中心限定在头部中心附近；
    #    分数还是太低就直接按头部推算（水平居中、顶端和刘海顶端对齐）
    if "back_hair" in parts:
        sh = sheet_of.get("back_hair")
        same = [p["scale"] for k, p in places.items() if sheet_of.get(k) == sh and p.get("method") == "match"]
        bscale = float(np.median(same)) if same else places["head_base"]["scale"]
        hp = places["head_base"]
        hw, hh = parts["head_base"].size
        win = (int(hp["cx"] - hw * hp["scale"] * 0.15), int(hp["cy"] - hh * hp["scale"] * 0.3),
               int(hp["cx"] + hw * hp["scale"] * 0.15), int(hp["cy"] + hh * hp["scale"] * 0.15))
        place("back_hair", window=win, scales=bscale * np.geomspace(0.93, 1.07, 5), factor=2)
        if places["back_hair"]["score"] < VISIBLE_SCORE:
            bw, bh = parts["back_hair"].size
            by0 = _bbox(footprint(parts["bangs"], places["bangs"], (Wd, H)))[1]
            places["back_hair"] = {"cx": hp["cx"], "cy": by0 + bh * bscale / 2, "scale": bscale, "rot": 0.0,
                                   "score": places["back_hair"]["score"], "method": "inferred",
                                   "from": "head_base + bangs"}
            log("  back_hair inferred from head_base / bangs")

    infer_expressions(places, parts, chosen, log)
    return {"places": places, "chosen": chosen, "face_window": face_win}


def infer_expressions(places: dict, parts: dict, chosen: dict, log=print, fscale: float | None = None) -> None:
    """没出现在 ref 里的表情变体，按同槽位已匹配变体对位。

    眼睛对齐“下沿中点”（半眯眼是上眼睑压下来，下沿不动）；其他对齐中心。
    缩放取已匹配表情零件的中位数（表情零件来自同一张图）。
    """
    if fscale is None:
        eyes = [p for n, p in places.items() if n.startswith("eye_") and p["method"] == "match"]
        fscale = float(np.mean([p["scale"] for p in eyes])) if eyes else 1.0
    # 先眼和嘴（参照 ref 里匹配到的那一款），再眉和腮红（没露出来时参照普通睁眼）
    order = sorted((n for n in parts if slot_of(n) and n not in places),
                   key=lambda n: ("eye", "mouth", "brow", "blush").index(slot_of(n)[0]))
    for n in order:
        slot, var, side = slot_of(n)
        w, h = parts[n].size
        ref_var = chosen.get(slot)
        if ref_var:
            anchor_name = f"{slot}_{ref_var}_{side}" if side else f"{slot}_{ref_var}"
        elif slot in ("brow", "blush"):
            anchor_name = f"eye_open_{side}"
        else:
            anchor_name = None
        if anchor_name not in places:
            log(f"  !! {n}: 没有可参照的零件，跳过")
            continue
        a = places[anchor_name]
        aw, ah = parts[anchor_name].size
        cx, cy = a["cx"], a["cy"]
        if slot == "eye":
            cy = a["cy"] + (ah * a["scale"] - h * fscale) / 2              # 下沿对齐
        elif anchor_name.startswith("eye_") and slot == "brow":
            top = a["cy"] - ah * a["scale"] / 2                          # 睁眼上沿往上留一点空
            cy = top - h * fscale / 2 - ah * a["scale"] * 0.12
        elif anchor_name.startswith("eye_") and slot == "blush":
            bottom = a["cy"] + ah * a["scale"] / 2
            cy = bottom + h * fscale * 0.3
            cx = a["cx"] + (-1 if side == "l" else 1) * aw * a["scale"] * 0.25   # 稍往外
        places[n] = {"cx": cx, "cy": cy, "scale": fscale, "rot": 0.0, "score": None,
                     "method": "inferred", "from": anchor_name}


# ---------------------------------------------------------------- 转轴

def _centroid(mask: np.ndarray):
    ys, xs = np.nonzero(mask)
    return float(xs.mean()), float(ys.mean())


def compute_pivots(parts: dict[str, Image.Image], places: dict) -> dict:
    """转轴初值（ref 坐标）。都是按零件形状估的，可以在 parts_map.json 的 overrides.pivots 里手改。"""
    def alpha(n):
        return np.asarray(parts[n])[..., 3] > 128

    def to_ref(n, pt):
        return [round(v, 1) for v in local_to_ref(pt, parts[n].size, places[n])]

    piv = {}
    # 脖子：头部底色最下面那截细脖子的顶端
    a = alpha("head_base")
    rows = np.nonzero(a.any(axis=1))[0]
    widths = a.sum(axis=1)
    wmax = widths.max()
    r = rows[-1]
    while r > rows[0] and widths[r] < wmax * 0.2:
        r -= 1
    xs = np.nonzero(a[rows[-1]])[0]
    piv["neck"] = to_ref("head_base", (float(xs.mean()), float(r)))
    # 肩：手臂零件里靠身体那一侧的上角（arm_l 在画面左，靠身体的是右上）
    for n, inner_right in (("arm_l", True), ("arm_r", False)):
        a = alpha(n)
        h, w = a.shape
        q = np.zeros_like(a)
        if inner_right:
            q[: h // 3, w * 2 // 3:] = True
        else:
            q[: h // 3, : w // 3] = True
        piv["shoulder_" + n[-1]] = to_ref(n, _centroid(a & q))
    # 胯：腿顶端 8% 的中心
    for n in ("leg_l", "leg_r"):
        a = alpha(n)
        rows = np.nonzero(a.any(axis=1))[0]
        band = np.zeros_like(a)
        band[rows[0]: rows[0] + max(2, len(rows) * 8 // 100)] = True
        piv["hip_" + n[-1]] = to_ref(n, _centroid(a & band))
    # 呆毛根：离头部中心最近的那一端
    hc = (places["head_base"]["cx"], places["head_base"]["cy"])
    for n, key in (("ahoge", "ahoge_root"),):
        a = alpha(n)
        ys, xs = np.nonzero(a)
        pts = np.array([local_to_ref((x, y), parts[n].size, places[n]) for x, y in zip(xs[::7], ys[::7])])
        d = np.hypot(pts[:, 0] - hc[0], pts[:, 1] - hc[1])
        near = pts[d <= np.percentile(d, 5)]
        piv[key] = [round(float(near[:, 0].mean()), 1), round(float(near[:, 1].mean()), 1)]
    # 花饰根：花朵（上半部分）的中心
    a = alpha("flower")
    rows = np.nonzero(a.any(axis=1))[0]
    band = np.zeros_like(a)
    band[rows[0]: rows[0] + len(rows) * 45 // 100] = True
    piv["flower_root"] = to_ref("flower", _centroid(a & band))
    # 刘海/鬓发根：顶端 10% 的中心
    for n, key in (("bangs", "bangs_root"), ("side_hair_l", "side_hair_l_root"), ("side_hair_r", "side_hair_r_root")):
        a = alpha(n)
        rows = np.nonzero(a.any(axis=1))[0]
        band = np.zeros_like(a)
        band[rows[0]: rows[0] + max(2, len(rows) // 10)] = True
        piv[key] = to_ref(n, _centroid(a & band))
    return piv


PIVOT_OF = {"head_base": "neck", "arm_l": "shoulder_l", "arm_r": "shoulder_r", "leg_l": "hip_l",
            "leg_r": "hip_r", "ahoge": "ahoge_root", "flower": "flower_root", "bangs": "bangs_root",
            "side_hair_l": "side_hair_l_root", "side_hair_r": "side_hair_r_root", "cheek_puff_l": "neck",
            "back_hair": "neck"}


# ---------------------------------------------------------------- rig.json

def layer_of(name: str) -> str:
    so = slot_of(name)
    if so:
        slot, _, side = so
        return f"{slot}_{side}" if side else slot
    return name


def write_rig(parts, places, pivots, chosen, cheek, sources, overrides) -> dict:
    W_, H_ = 1086, 1448
    rig = {
        "version": 1,
        "canvas": [W_, H_],
        "source": "assets/sprites/raw/v3/ref.png",
        "coords": "ref 像素坐标；零件先 scale 缩放、再绕自身中心逆时针转 rot 度，中心放在 (cx, cy)",
        "layers": LAYERS,
        "slots": {s: [v for v in vs if any(slot_of(n) == (s, v, side) for n in parts for side in ("", "l", "r"))]
                  for s, vs in EXPR_SLOTS.items()},
        "faces": {"neutral": FACES["neutral"],
                  "smug": {**FACES["smug"], **{k: chosen[k] for k in ("brow", "blush") if chosen.get(k)}}},
        "pivots": pivots,
        "parts": {},
        "cheek_puff": {
            "active": "l",
            "l": {"part": "cheek_puff_l", "above": "side_hair_l"},
            "r": {"part": "cheek_puff_l", "mirror_x_about": "head_base", "above": "side_hair_r",
                  "note": "预留：屏幕另一侧时把左侧鼓脸颊水平镜像到右边，图层放在右鬓发之上（头部底色同时镜像）"},
            "cut": cheek,
        },
        "notes": {
            "blink": "普通眨眼不用新零件：把当前睁眼零件 eye_open_* 以下沿为轴纵向压缩实现",
            "head_base_alt": "B02 为备用头部底色，不参与拼图",
            "left_right": "左右一律指画面左/右",
        },
    }
    for n in sorted(parts, key=lambda n: (LAYERS.index(layer_of(n)) if layer_of(n) in LAYERS else 99, n)):
        if n not in places:
            continue
        p = places[n]
        ov = overrides.get("parts", {}).get(n, {})
        p = {**p, **ov, "method": "override"} if ov else p
        lay = layer_of(n)
        entry = {
            "file": f"parts/{n}.png",
            "size": list(parts[n].size),
            "layer": lay,
            "z": LAYERS.index(lay) if lay in LAYERS else None,
            "cx": round(p["cx"], 2), "cy": round(p["cy"], 2),
            "scale": round(p["scale"], 4), "rot": round(p["rot"], 2),
            "score": None if p.get("score") is None else round(p["score"], 3),
            "method": p["method"],
            "parent": PARENTS.get(n, "head_base"),
        }
        if p.get("from"):
            entry["inferred_from"] = p["from"]
        if n in PIVOT_OF:
            entry["pivot"] = PIVOT_OF[n]
        if n in sources:
            entry["sheet"] = sources[n]["sheet"]
            entry["blocks"] = sources[n]["blocks"]
        rig["parts"][n] = entry
    pov = overrides.get("pivots", {})
    rig["pivots"].update(pov)
    RIG_V1_FILE.write_text(json.dumps(rig, indent=1, ensure_ascii=False), encoding="utf-8")
    return rig


def load_parts() -> dict[str, Image.Image]:
    return {p.stem: Image.open(p).convert("RGBA") for p in sorted(PARTS.glob("*.png"))}


MATCH_CACHE = BUILD / "places.json"


def cmd_rig(reuse: bool = False) -> dict:
    """reuse=True 时跳过模板匹配（约 6 分钟），直接用上次存在 build/v3/places.json 里的结果，
    只重算鼓脸颊、转轴和 rig.json，调 overrides 时用。"""
    mapping = read_map()
    sources = json.loads((OUT / "sources.json").read_text(encoding="utf-8"))
    parts = {k: v for k, v in load_parts().items() if k in sources and k != "head_base_alt"}
    ref_rgb = np.asarray(Image.open(RAW / "ref.png").convert("RGB"))
    if reuse and MATCH_CACHE.exists():
        res = json.loads(MATCH_CACHE.read_text(encoding="utf-8"))
        print(f"reuse {MATCH_CACHE.relative_to(ROOT)}")
    else:
        print("matching ...")
        res = build_rig(ref_rgb, parts, {n: s["sheet"] for n, s in sources.items()})
        BUILD.mkdir(parents=True, exist_ok=True)
        MATCH_CACHE.write_text(json.dumps(res, indent=1), encoding="utf-8")
    places, chosen = res["places"], res["chosen"]

    # 鼓脸颊：从头部底色拷出来；切口放在左鬓发右边缘往里一点，让羽化落在没被头发盖住的皮肤上
    head = parts["head_base"]
    ha = np.asarray(head)[..., 3]
    cut = cheek_cut(ha)
    hp = places["head_base"]
    sl = np.asarray(render(parts["side_hair_l"], places["side_hair_l"], (1086, 1448)))[..., 3] > 128
    # 鼓包所在行（ref 坐标）上，左鬓发的最右端
    _, by = local_to_ref((cut["bulge_x"], cut["bulge_row"]), head.size, hp)
    y0r, _ = int(by - 30), None
    rows = sl[max(0, y0r): int(by + 30)]
    hair_right = int(np.nonzero(rows.any(axis=0))[0].max()) if rows.any() else None
    if hair_right is not None:
        # ref → 头部底色原图坐标（只有缩放和平移，头部底色不旋转）
        u = (hair_right + 8 - hp["cx"]) / hp["scale"] + head.width / 2
        cut_x = int(round(u)) + CHEEK_FEATHER
    else:
        cut_x = cut["indent_x"] + 40
    cut["cut_x"] = cut_x
    cheek = make_cheek(head, cut["top"], cut_x, bottom=cut["bottom"] + CHEEK_FEATHER)
    ox, oy = cheek.info["offset"]
    save_png(cheek, PARTS / "cheek_puff_l.png")
    parts["cheek_puff_l"] = cheek
    ccx, ccy = local_to_ref((ox + cheek.width / 2, oy + cheek.height / 2), head.size, hp)
    places["cheek_puff_l"] = {"cx": ccx, "cy": ccy, "scale": hp["scale"], "rot": hp["rot"],
                              "score": None, "method": "derived", "from": "head_base"}
    cut["offset_in_head_base"] = [ox, oy]
    sources["cheek_puff_l"] = {"blocks": sources["head_base"]["blocks"], "sheet": sources["head_base"]["sheet"],
                               "derived": "从头部底色拷出的鼓脸颊"}

    tuning = {**DEFAULT_TUNING, **mapping.get("tuning", {})}
    clips = apply_tuning(parts, places, chosen, tuning)
    pivots = compute_pivots(parts, places)
    rig = write_rig(parts, places, pivots, chosen, cut, sources, mapping.get("overrides", {}))
    rig["tuning"] = {k: v for k, v in tuning.items()}
    rig["tuning"]["_note"] = TUNING_NOTE
    rig["render_clip"] = clips
    RIG_V1_FILE.write_text(json.dumps(rig, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"rig.json: {len(rig['parts'])} parts; chosen expression in ref: {chosen}")
    return rig


# ---------------------------------------------------------------- 人工微调（2026-11-05 用户看对比图后提出）

DEFAULT_TUNING = {
    "eye_scale": 1.4,        # 所有眼睛零件以下沿中点为轴放大
    "eye_spread_px": 12,     # 每只眼再往脸外侧移（ref 像素，按 1.4 倍眼在 ref 里重新匹配测得）
    "eye_dy_px": -8,         # 眼睛整体上移
    "cheek_scale": 1.3,      # 鼓脸颊以右侧切口中点为轴放大，鼓包往外长
    "cheek_dx_px": -14,      # 鼓脸颊再往画面左移
    "head_dy_px": 12,        # 头部组整体下移，下巴压到领子上
    "neck_clip_px": 3,       # 头部底色只画到下巴下沿往下这么多（零件原图像素），多出的脖子不画
    "head_group_scale": 1.1, # 头部组以脖子转轴为中心整体放大
}
TUNING_NOTE = ("看对比图后的人工微调，顺序：眼睛放大/外移 → 眉毛按新眼睛重推 → 鼓脸颊放大外移 → "
               "头部组下移 → 头部组以脖子为中心放大；parts 里的 cx/cy/scale 已是微调后的最终值。"
               "腮红图层已移到鬓发和鼓脸颊之上。")
HEAD_GROUP_EXTRA = {"head_base", "back_hair", "side_hair_l", "side_hair_r", "bangs", "flower", "ahoge", "cheek_puff_l"}


def in_head_group(name: str) -> bool:
    return name in HEAD_GROUP_EXTRA or slot_of(name) is not None


def neck_row(alpha: np.ndarray) -> int:
    """头部底色里下巴下沿那一行（再往下是细脖子）。和 compute_pivots 里脖子转轴的算法一致。"""
    rows = np.nonzero(alpha.any(axis=1))[0]
    widths = alpha.sum(axis=1)
    r = rows[-1]
    while r > rows[0] and widths[r] < widths.max() * 0.2:
        r -= 1
    return int(r)


def scale_about(p: dict, ox: float, oy: float, k: float) -> None:
    p["cx"] = ox + (p["cx"] - ox) * k
    p["cy"] = oy + (p["cy"] - oy) * k
    p["scale"] *= k


def apply_tuning(parts: dict, places: dict, chosen: dict, t: dict, log=print) -> dict:
    """把人工微调参数作用到 places 上（原地修改），返回渲染裁切参数。零件原图不改。"""
    eyes = [n for n in places if n.startswith("eye_")]
    mid = np.mean([places[n]["cx"] for n in eyes])
    fscale = float(np.mean([places[n]["scale"] for n in eyes if places[n]["method"] == "match"]))
    for n in eyes:
        p = places[n]
        h = parts[n].size[1] * p["scale"]
        bottom = p["cy"] + h / 2
        scale_about(p, p["cx"], bottom, t["eye_scale"])
        p["cx"] += t["eye_spread_px"] * (1 if p["cx"] > mid else -1)
        p["cy"] += t["eye_dy_px"]
        p["method"] = p["method"] + "+tuned"
    # 眉毛参照睁眼推出来的，眼睛变了要重推
    for n in [n for n in places if n.startswith("brow_") and places[n]["method"] == "inferred"]:
        del places[n]
    infer_expressions(places, parts, chosen, log=lambda *_: None, fscale=fscale)   # 眉毛不跟着放大
    # 鼓脸颊：以右侧切口中点为轴放大，再外移
    cp = places["cheek_puff_l"]
    w, h = parts["cheek_puff_l"].size
    edge_x = cp["cx"] + w * cp["scale"] / 2
    scale_about(cp, edge_x, cp["cy"], t["cheek_scale"])
    cp["cx"] += t["cheek_dx_px"]
    cp["method"] = "derived+tuned"
    # 头部组：先下移，再以（下移后的）脖子转轴为中心放大
    group = [n for n in places if in_head_group(n)]
    for n in group:
        places[n]["cy"] += t["head_dy_px"]
    r = neck_row(np.asarray(parts["head_base"])[..., 3] > 128)
    nx, ny = compute_pivots(parts, places)["neck"]      # 和转轴表里的“脖子”是同一个点
    for n in group:
        scale_about(places[n], nx, ny, t["head_group_scale"])
    log(f"  tuning: neck=({nx:.0f},{ny:.0f}), head group {len(group)} parts")
    return {"head_base": neck_clip(np.asarray(parts["head_base"])[..., 3] > 128, int(t["neck_clip_px"]))}


def neck_clip(alpha: np.ndarray, extra: int = 3) -> dict:
    """头部底色的脖子裁切参数（零件原图坐标）。

    下巴轮廓线在脖子那一段是断开的，皮肤直接连到细脖子上。所以除了“max_row 以下全不画”，
    还要在脖子宽度 [x0, x1] 内把下巴轮廓下沿 chin_row 以下也去掉，下巴才直接坐在领子上。
    """
    r = neck_row(alpha)
    stub = np.nonzero(alpha[min(r + 4, alpha.shape[0] - 1)])[0]
    x0, x1 = int(stub.min()), int(stub.max())
    sides = [np.nonzero(alpha[:, x])[0].max() for x in (x0 - 3, x1 + 3) if 0 <= x < alpha.shape[1] and alpha[:, x].any()]
    chin = int(min(sides)) if sides else r
    return {"max_row": r + extra, "neck_x": [x0, x1], "chin_row": chin,
            "note": "渲染时 max_row 以下不画；neck_x 范围内 chin_row 以下也不画（零件原图坐标）"}


def clipped(parts: dict, name: str, clips: dict) -> Image.Image:
    img = parts[name]
    c = clips.get(name)
    if not c:
        return img
    a = np.asarray(img).copy()
    a[c["max_row"] + 1:] = 0
    if "neck_x" in c:
        x0, x1 = c["neck_x"]
        a[c["chin_row"] + 1:, x0:x1 + 1] = 0
    return Image.fromarray(a)


# ---------------------------------------------------------------- 拼图与对比

def compose(rig: dict, parts: dict[str, Image.Image], face: dict) -> Image.Image:
    size = tuple(rig["canvas"])
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    want = {}
    for slot, var in face.items():
        if var:
            want[slot] = var
    for lay in rig["layers"]:
        names = [n for n, p in rig["parts"].items() if p["layer"] == lay]
        for n in names:
            so = slot_of(n)
            if so and want.get(so[0]) != so[1]:
                continue
            p = rig["parts"][n]
            img = clipped(parts, n, rig.get("render_clip", {}))
            paste_center(canvas, transform(img, p["scale"], p["rot"]), p["cx"], p["cy"])
    return canvas


def on_white(img: Image.Image) -> Image.Image:
    bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
    bg.alpha_composite(img)
    return bg.convert("RGB")


def side_by_side(images: list[tuple[str, Image.Image]], gap: int = 24) -> Image.Image:
    """几张同尺寸的图左右并排，每张上方写标题。"""
    w, h = images[0][1].size
    out = Image.new("RGB", (w * len(images) + gap * (len(images) - 1), h + 60), (255, 255, 255))
    d = ImageDraw.Draw(out)
    f = _font(34)
    for i, (title, img) in enumerate(images):
        x = i * (w + gap)
        out.paste(img.convert("RGB"), (x, 60))
        d.text((x + 16, 12), title, fill=(0, 0, 0), font=f)
    return out


def pivot_view(rig: dict, parts, comp: Image.Image) -> Image.Image:
    img = on_white(comp).convert("RGBA")
    d = ImageDraw.Draw(img)
    f = _font(22)
    for n, p in rig["parts"].items():
        if slot_of(n):
            continue
        layer = render(parts[n], p, img.size)
        bb = layer.getbbox()
        if bb:
            d.rectangle(bb, outline=(60, 120, 255, 255), width=2)
    for k, (x, y) in rig["pivots"].items():
        d.ellipse([x - 8, y - 8, x + 8, y + 8], fill=(255, 0, 80, 255), outline=(255, 255, 255, 255), width=2)
        d.text((x + 10, y - 12), k, fill=(200, 0, 60, 255), font=f, stroke_width=3, stroke_fill=(255, 255, 255, 255))
    # 鼓脸颊范围（绿框）
    bb = render(parts["cheek_puff_l"], rig["parts"]["cheek_puff_l"], img.size).getbbox()
    if bb:
        d.rectangle(bb, outline=(0, 200, 120, 255), width=3)
        d.text((bb[0], bb[1] - 28), "cheek_puff_l", fill=(0, 150, 90, 255), font=f, stroke_width=3,
               stroke_fill=(255, 255, 255, 255))
    return img.convert("RGB")


def face_closeup(rig: dict, comps: list[tuple[str, Image.Image]], ref_rgb: np.ndarray) -> Image.Image:
    """脸部特写并排（放大 1.5 倍）：各张拼图和 ref 的同一区域。"""
    hp = rig["parts"]["head_base"]
    x0, y0 = int(hp["cx"] - 360), int(hp["cy"] - 260)
    box = (max(0, x0), max(0, y0), min(rig["canvas"][0], x0 + 720), min(rig["canvas"][1], y0 + 520))
    k = 1.5
    def crop(img):
        c = img.crop(box)
        return c.resize((int(c.width * k), int(c.height * k)), Image.LANCZOS)
    items = [(t, crop(on_white(c))) for t, c in comps] + [("ref", crop(Image.fromarray(ref_rgb)))]
    return side_by_side(items)


def cmd_compose() -> None:
    rig = json.loads(RIG_V1_FILE.read_text(encoding="utf-8"))
    parts = load_parts()
    ref_rgb = np.asarray(Image.open(RAW / "ref.png").convert("RGB"))
    BUILD.mkdir(parents=True, exist_ok=True)
    ref_img = Image.fromarray(ref_rgb)
    comps = []
    for face in ("neutral", "smug"):
        comp = compose(rig, parts, rig["faces"][face])
        comps.append((face, comp))
        on_white(comp).save(BUILD / f"{face}.png")
        side_by_side([(face, on_white(comp)), ("ref", ref_img)]).save(BUILD / f"compare_{face}.png")
        if face == "smug":
            pivot_view(rig, parts, comp).save(BUILD / "pivots.png")
    side_by_side([(t, on_white(c)) for t, c in comps] + [("ref", ref_img)]).save(BUILD / "compare_all.png")
    face_closeup(rig, comps, ref_rgb).save(BUILD / "compare_faces.png")
    for old in ("cheek_cut.png",):    # 旧版切口特写已不准（鼓脸颊另外放大外移了），删掉免得误看
        (BUILD / old).unlink(missing_ok=True)
    print(f"composites -> {BUILD.relative_to(ROOT)}")


def main(argv: list[str] | None = None) -> None:
    import argparse
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=["extract", "name", "rig", "compose", "all"])
    p.add_argument("--reuse", action="store_true", help="rig：沿用上次的匹配结果，只重算切口、转轴和 rig.json")
    args = p.parse_args(argv)
    if args.cmd == "all":
        cmd_name()
        cmd_rig(args.reuse)
        cmd_compose()
    elif args.cmd == "rig":
        cmd_rig(args.reuse)
    else:
        {"extract": cmd_extract, "name": cmd_name, "compose": cmd_compose}[args.cmd]()


if __name__ == "__main__":
    main()
