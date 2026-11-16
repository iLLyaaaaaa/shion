"""S8 第 2 项：working 抱电脑（assets/sprites/raw/v3/s6/working-hold.png，1122x1402）。

python -m tools.v3_hold build [--out build/v3/integrate/s8/hold]

1. 把原件对位到 rig 画布（1086x1448）：用头、脸、身体、腿的未改动部分拟合一个仿射，
   一次重采样完成补白边和缩放（不先做等比补边）。
2. “双臂 + 笔记本电脑”整块 = 对位后的新图与“去掉双臂的 neutral”不同的那一块。
3. 写 slices/arms_hold.png 和 rig.json 的 part ``arms_hold``（父级 body，跟身体走，不参与手臂摆动）。
只读 raw；不单独出道具零件图。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as nd

from tools.v3_extract import remove_white_bg
from tools.v3_replace_expressions import align_head
from v3proto.render import DEFAULT_RIG, Rig

SOURCE = Path("assets/sprites/raw/v3/s6/working-hold.png")
OUT = Path("build/v3/integrate/s8/hold")
ARMS = ("arm_l", "arm_r")
ROI = (100, 660, 990, 1140)      # 双臂和电脑可能出现的范围（rig 坐标）
ARM_ZONE = (120, 650, 960, 1060)  # 拟合时排除
THRESHOLD = 40
OPEN_ITERATIONS = 6
OPEN_GROW = 4
# 新画的领口、缎带、裙边与现有身体有几像素错位，会形成和电脑相连的碎片；这些位置本来就是
# 现有身体的一部分（rig 坐标 x0, y0, x1, y1，按 build/v3/integrate/s8/hold/aligned-vs-current.png 量）。
EXCLUDE = (
    (440, 600, 845, 686),   # 电脑上缘以上：领口
    (456, 600, 520, 760),   # 电脑左上角旁：领口和领巾
    (838, 600, 1000, 820),  # 电脑右侧：缎带
    (786, 925, 1000, 1100), # 右袖口外侧
    (772, 950, 1000, 1100), # 右袖口下方的裙边碎线
    (200, 925, 300, 1010),  # 左袖口外侧的碎点
)
EXCLUDE_POLYGONS = (
    # 电脑左上斜边以上：领口条纹
    ((456, 686), (700, 686), (700, 692), (690, 694), (528, 742), (456, 742)),
)
PART = "arms_hold"


def without_arms(rig, expression="neutral"):
    """白底 RGB 和 RGBA：neutral 去掉 arm_l / arm_r。"""
    original = rig.active

    def active(expr, underlays_only=False, arms="default"):
        return [n for n in original(expr, underlays_only, arms) if n not in ARMS]

    rig.active = active
    try:
        rgba = rig.rest(expression)
    finally:
        del rig.active
    white = Image.new("RGBA", rig.size, "white")
    white.alpha_composite(rgba)
    return np.asarray(white.convert("RGB")), np.asarray(rgba)


def align(rig, source):
    """(对位后的 RGB, 仿射参数)。"""
    full = Image.new("RGBA", rig.size, "white")
    full.alpha_composite(rig.rest("neutral"))
    reference = np.asarray(full.convert("RGB"))
    silhouette = np.asarray(rig.rest("neutral"))[..., 3] > 128
    keep = silhouette.copy()
    x0, y0, x1, y1 = ARM_ZONE
    keep[y0:y1, x0:x1] = False
    aligned, params = align_head(reference, source, keep, rows=(35, 1420))
    return aligned, params, reference


def excluded(shape):
    out = np.zeros(shape, bool)
    for ex0, ey0, ex1, ey1 in EXCLUDE:
        out[ey0:ey1, ex0:ex1] = True
    image = Image.new("L", (shape[1], shape[0]))
    from PIL import ImageDraw
    for polygon in EXCLUDE_POLYGONS:
        ImageDraw.Draw(image).polygon(polygon, fill=255)
    return out | (np.asarray(image) > 0)


def block_mask(aligned, noarms):
    delta = np.abs(aligned.astype(int) - noarms.astype(int)).max(-1)
    x0, y0, x1, y1 = ROI
    roi = np.zeros(delta.shape, bool)
    roi[y0:y1, x0:x1] = True
    mask = (delta > THRESHOLD) & roi
    mask &= ~excluded(mask.shape)
    # 新画和现有身体在领口、裙边、缎带边缘有 1～3 像素的错位，形成细长碎片：
    # 先把整块（袖子、手、电脑都是粗块）作为“芯”，碎片在开运算里消失，
    # 再向外长回至多 OPEN_GROW 像素（不超出原差异范围）。
    mask = nd.binary_closing(mask, iterations=3)
    core = nd.binary_opening(mask, iterations=OPEN_ITERATIONS)
    labels, count = nd.label(core)
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    core = np.isin(labels, np.flatnonzero(sizes >= 3000))
    keep = nd.binary_dilation(core, iterations=OPEN_GROW) & mask
    keep = nd.binary_fill_holes(keep)
    keep = nd.binary_dilation(keep, iterations=1) & roi
    keep &= ~excluded(keep.shape)
    return keep, delta


def build(rig, out=OUT):
    path = rig.path
    with Image.open(SOURCE) as im:
        source = np.asarray(im.convert("RGB"))
    aligned, params, reference = align(rig, source)
    noarms, noarms_rgba = without_arms(rig)
    mask, delta = block_mask(aligned, noarms)
    person = remove_white_bg(aligned)[..., 3]
    # 与背景相邻的一圈用去白底的半透明，其余整块不透明
    background = noarms_rgba[..., 3] < 8
    ring = nd.binary_dilation(mask, iterations=2) & background & (person > 0)
    alpha = np.where(mask, 255, 0).astype(np.uint8)
    alpha[ring] = person[ring]
    alpha[mask & background] = np.minimum(alpha[mask & background], person[mask & background])
    alpha[alpha < 12] = 0   # 去白底的抗锯齿尾巴会在块外留下单个像素的碎点
    labels, _ = nd.label(alpha > 0)
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    alpha[~np.isin(labels, np.flatnonzero(sizes >= 3000))] = 0
    rgba = np.dstack([aligned, alpha])
    rgba[alpha == 0] = 0
    box = Image.fromarray(rgba).getbbox()
    (path.parent / "slices").mkdir(exist_ok=True)
    Image.fromarray(rgba).crop(box).save(path.parent / "slices" / "arms_hold.png")
    data = json.loads(path.read_text(encoding="utf-8"))
    template = data["parts"]["arm_l"]
    data["parts"][PART] = {"file": "slices/arms_hold.png", "source": "hold_slice", "layer": template["layer"],
                           "z": template["z"], "x": box[0], "y": box[1],
                           "size": [box[2] - box[0], box[3] - box[1]], "parent": "body"}
    data["hold"] = {"source": SOURCE.as_posix(), "affine": [round(float(v), 6) for v in params]}
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    # 预览：切块灰底、并排对比、与原参考的头部残差
    out.mkdir(parents=True, exist_ok=True)
    gray = Image.new("RGBA", rig.size, "#8a8f98")
    gray.alpha_composite(Image.fromarray(rgba))
    gray.crop((60, 560, 1030, 1200)).save(out / "block-on-gray.png")
    side = Image.new("RGB", (970 * 2 + 10, 640), "#ddd")
    side.paste(Image.fromarray(aligned).crop((60, 560, 1030, 1200)), (0, 0))
    side.paste(Image.fromarray(reference).crop((60, 560, 1030, 1200)), (980, 0))
    side.save(out / "aligned-vs-current.png")
    head = np.asarray(rig.rest("neutral"))[..., 3] > 128
    report = {"affine": [round(float(v), 4) for v in params], "box": list(box),
              "block_pixels": int(mask.sum()),
              "residual_mean": {name: round(float(np.abs(aligned.astype(int) - reference.astype(int)).max(-1)[y0:y1][head[y0:y1]].mean()), 1)
                                for name, (y0, y1) in {"head": (35, 425), "legs": (1060, 1420)}.items()}}
    (out / "hold-build.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=1))


def overlap_report(rig):
    """块和头发类部件的重叠（决定层级）。"""
    part = rig.parts[PART]
    block = np.zeros(rig.size[::-1], bool)
    a = np.asarray(Image.open(rig.path.parent / part["file"]).convert("RGBA"))[..., 3] > 128
    block[part["y"]:part["y"] + a.shape[0], part["x"]:part["x"] + a.shape[1]] = a
    result = {}
    for name in ("side_hair_l", "side_hair_r", "back_hair", "ribbon", "flower", "bangs", "head_skin"):
        q = rig.parts[name]
        other = np.zeros(rig.size[::-1], bool)
        b = np.asarray(rig.images[name])[..., 3] > 128
        other[q["y"]:q["y"] + b.shape[0], q["x"]:q["x"] + b.shape[1]] = b
        result[name] = int((block & other).sum())
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    if args.cmd == "build":
        build(Rig(DEFAULT_RIG), args.out)
        print("overlap with head parts:", overlap_report(Rig(DEFAULT_RIG)))


if __name__ == "__main__":
    main()
