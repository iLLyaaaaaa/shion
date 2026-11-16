"""S8：右鼓版脸部底板（assets/sprites/raw/v3/s6/head-right-plate.png）。

python -m tools.v3_right_plate diff  [--out build/v3/integrate/s8]
    新图与当前左鼓原图（smug，S0 定稿）的差异热图和统计。
python -m tools.v3_right_plate build
    对位、切右侧 head_skin / 干净底板 / 捏脸素材，登记到 rig.json right_side。

只读 raw；左侧现有素材一个不动。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as nd

from v3proto.mirror import EYE_MIDLINE_SUM
from v3proto.render import DEFAULT_RIG, Rig

SOURCE = Path("assets/sprites/raw/v3/s6/head-right-plate.png")
OUT = Path("build/v3/integrate/s8")
# 允许改动的两块（rig 坐标）：原左脸颊一带、新右脸颊一带。
LEFT_ZONE = (90, 440, 470, 800)
RIGHT_ZONE = (EYE_MIDLINE_SUM - 470, 440, EYE_MIDLINE_SUM - 90, 800)
# 下颌带（rig 坐标 x0, y0, x1, y1）：新鼓包的下缘到下巴缺口之间。neutral 的睁眼底板（旧稿）在这里的下颌描线比新画低约
# 15 像素（实测 x=590..680：新画 y=647..636，neutral 底板 y≈662..651），到 x≈685 突然接上新画的粗描线，看起来
# 鼓包和下巴“断开”。其余睁眼底板（smug/teary/angry）和 plate 路径的表情（happy 等）都在新画 1 像素内。
# 带里的睁眼底板一律取干净底板（已按新画重画）：左边缘 571 = 右侧改动框的内墙，刚好盖住旧稿里比新画低 12 像素的
# 下巴缺口（x=572..590）；右边缘 724 在重画区里（两者本来就相同）。边缘 JAW_FEATHER 像素内渐变，不留直角台阶。
JAW_BAND = (571, 596, 724, 700)
JAW_FEATHER = 4
# 新鼓包连描线的外轮廓椭圆（rig 坐标 cx, cy, rx, ry；cheek 框 [614,502,789,642] 外扩）。清眼睛时这里面的像素不动：
# 右眼的白眼角正好贴在鼓包上缘，旧做法把靠近眼睛的非肤色像素（含鼓包上缘的描线）一起换成了肤色。
BULGE = (701, 572, 93, 76)
THRESHOLD = 40
LID_MARGIN = 12    # reference pixels around an eye polygon that count as the eye window


def smooth_fill(image, valid, hole):
    """hole 里的像素用周围 valid 像素的高斯加权平均补上（σ 由小到大，够到有效像素为止）。
    比“取最近的肤色像素”平滑：后者在大块空洞里会拉出放射状的条纹，眼睛比画稿小的表情（tired、bored 等）会露出来。"""
    result = image.copy()
    pixels = image.astype(np.float32)
    done = np.zeros(hole.shape, bool)
    for sigma in (2, 4, 8, 16, 32, 64):
        weight = nd.gaussian_filter(valid.astype(np.float32), sigma)
        take = hole & ~done & (weight > 0.12)
        if take.any():
            mean = np.stack([nd.gaussian_filter(pixels[..., k] * valid, sigma) for k in range(3)], -1)
            result[take] = np.rint(mean[take] / weight[take][:, None]).astype(np.uint8)
            done |= take
    rest = hole & ~done
    if rest.any():
        _, near = nd.distance_transform_edt(~valid, return_indices=True)
        result[rest] = image[tuple(near)][rest]
    return result


def reference(rig):
    ref = Image.new("RGBA", rig.size, "white")
    ref.alpha_composite(rig.rest("smug", original=True))
    return np.asarray(ref.convert("RGB"))


def load_source(rig, path=SOURCE):
    with Image.open(path) as im:
        source = np.asarray(im.convert("RGB"))
    if source.shape[:2] != rig.size[::-1]:
        raise ValueError(f"right plate must match the rig canvas, got {source.shape[1]}x{source.shape[0]}")
    return source


def zone_mask(shape, zones=(LEFT_ZONE, RIGHT_ZONE)):
    mask = np.zeros(shape, bool)
    for x0, y0, x1, y1 in zones:
        mask[y0:y1, x0:x1] = True
    return mask


def diff_report(ref, source, out):
    delta = np.abs(source.astype(int) - ref.astype(int)).max(-1)
    changed = delta > THRESHOLD
    zones = zone_mask(changed.shape)
    # 描边级的 1～2 像素抖动不算改动：开运算后剩下的才是成片改动。
    solid = nd.binary_opening(changed, iterations=2)
    labels, count = nd.label(solid & ~zones)
    blobs = []
    for i, box in enumerate(nd.find_objects(labels), 1):
        size = int((labels[box] == i).sum())
        if size >= 60:
            blobs.append({"box": [box[1].start, box[0].start, box[1].stop, box[0].stop], "pixels": size})
    blobs.sort(key=lambda b: -b["pixels"])
    report = {
        "threshold": THRESHOLD,
        "changed": int(changed.sum()),
        "changed_in_zones": int((changed & zones).sum()),
        "changed_outside": int((changed & ~zones).sum()),
        "solid_in_zones": int((solid & zones).sum()),
        "solid_outside": int((solid & ~zones).sum()),
        "zones": {"left": LEFT_ZONE, "right": RIGHT_ZONE},
        "outside_blobs": blobs[:20],
    }
    out.mkdir(parents=True, exist_ok=True)
    gray = source.mean(-1, keepdims=True) * .35 + 255 * .65
    heat = np.repeat(gray, 3, -1)
    level = np.clip(delta / 160, 0, 1)[..., None]
    heat = heat * (1 - level) + np.array([220, 0, 0]) * level
    image = Image.fromarray(heat.astype(np.uint8))
    draw = ImageDraw.Draw(image)
    for zone in (LEFT_ZONE, RIGHT_ZONE):
        draw.rectangle(zone, outline=(0, 90, 255), width=3)
    image.save(out / "right-plate-diff-full.png")
    head = image.crop((60, 0, 1030, 860))
    head.resize((head.width * 3 // 4, head.height * 3 // 4), Image.Resampling.LANCZOS).save(out / "right-plate-diff.png")
    (out / "right-plate-diff.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def flood_skin(rgb):
    """Face skin reachable from the chin without crossing ink (holes filled)."""
    c = rgb.astype(np.int16)
    wall = nd.binary_closing(c.min(-1) < 150, iterations=1)
    labels, _ = nd.label(~wall)
    if labels[640, 500] == 0:
        raise ValueError("skin seed lies on ink")
    return nd.binary_fill_holes(labels == labels[640, 500])


def skin_with_contour(rgb, domain):
    """Skin plus the dark outline that belongs to it. No hair: hair is lighter than ink."""
    distance = nd.distance_transform_edt(~domain)
    return domain | ((distance <= 15) & (rgb.astype(int).max(-1) < 210))


def open_eye_colour(rgba):
    """Orange iris pixels (opaque): the painting's open smug eyes, never wanted under closed ones."""
    c = rgba[..., :3].astype(int)
    return (rgba[..., 3] > 128) & (c[..., 0] > 200) & (c[..., 1] > 100) & (c[..., 1] < 200) & (c[..., 2] < 100)


def on_canvas(size, image, origin):
    canvas = Image.new("RGBA", size)
    canvas.alpha_composite(image, origin)
    return canvas


def fit_cheek(ref_domain, new_domain):
    """(mirror_sum, dy): reflect + shift that lays the painted right bulge on the left one."""
    from tools.v3_cheek import BOX
    rows = np.arange(BOX[1] + 9, BOX[3] - 40)
    left = np.array([np.flatnonzero(ref_domain[y]).min() for y in rows])
    best = None
    for dy in range(-40, 41):
        right = np.array([np.flatnonzero(new_domain[y + dy]).max() for y in rows])
        total = left + right
        mirror_sum = int(round(float(np.median(total))))
        cost = float(np.abs(total - mirror_sum).mean())
        if best is None or cost < best[0]:
            best = (cost, mirror_sum, dy)
    return best[1], best[2], best[0]


def right_smug_eyes(rig):
    return [n for n in rig.face_parts("smug") if rig.parts[n]["role"].startswith("eye")]


def right_face_assets(canvas, clean, protection, box, mirror_sum, dy):
    """(mask, texture, hit) of the painted right bulge for one expression.

    mask: what leaves the face when the cheek is pulled (skin and its own outline,
    without the fixed eye window). texture: the same surface with the eye window
    taken from the clean plate, so no eye pixel is ever dragged along.
    """
    rgba = np.asarray(canvas)
    rgb = rgba[..., :3].astype(int)
    wall = nd.binary_closing((rgb.min(-1) < 150) | (rgba[..., 3] < 128), iterations=1)
    labels, _ = nd.label(~wall)
    if labels[640, 541] == 0:
        raise ValueError("skin seed lies on ink")
    domain = nd.binary_fill_holes(labels == labels[640, 541])
    distance = nd.distance_transform_edt(~domain)
    visible = domain | ((distance <= 9) & (rgb.max(-1) < 210) & (rgba[..., 3] > 128))
    x0, y0, x1, y1 = box
    crop = (slice(y0, y1), slice(x0, x1))
    features = np.asarray(protection)[crop] > 0
    # Colour comes from the clean plate: it has no eye to smear and keeps the blush whole.
    color = np.asarray(clean)[crop][..., :3].copy()
    alpha = (visible[crop] * 255).astype(np.uint8)
    texture = np.dstack([color, alpha])
    texture[alpha == 0] = 0
    mask = alpha.copy()
    mask[features] = 0
    yy, xx = np.indices(mask.shape)
    xx += x0
    yy += y0
    hit = (nd.binary_erosion(mask > 200, iterations=3) & (mirror_sum - xx < 385)
           & (yy >= 570 + dy) & (yy <= 650 + dy))
    return Image.fromarray(mask), Image.fromarray(texture), Image.fromarray((hit * 255).astype(np.uint8))


def build(rig, out=OUT):
    from tools.v3_cheek import BOX, REGION, eye_windows
    from v3proto.face import plate_face
    from v3proto.mirror import cut_old_cheek, head_layer_names, mirrored_box

    path = rig.path
    folder = path.parent / "right"
    folder.mkdir(exist_ok=True)
    size = rig.size
    ref = reference(rig)
    source = load_source(rig)
    left_zone, right_zone = zone_mask(size[::-1], (LEFT_ZONE,)), zone_mask(size[::-1], (RIGHT_ZONE,))
    zones = left_zone | right_zone
    white = source.min(-1) > 246

    ref_skin, new_skin = flood_skin(ref), flood_skin(source)
    old_vis, new_vis = skin_with_contour(ref, ref_skin), skin_with_contour(source, new_skin)
    mirror_sum, dy, fit_cost = fit_cheek(ref_skin, new_skin)
    eyes = nd.binary_dilation(np.asarray(eye_windows(size, "smug")) > 0, iterations=3)
    # Every expression's eye window with the lids (the polygons are tight). The
    # painting shows open smug eyes: inside these windows no open-eye colour (iris,
    # white of the eye, lashes) may come from it. Skin and blush may: the new bulge
    # reaches up under the eyes, and clipping it there would cut its top flat.
    own_windows = {face: nd.binary_dilation(np.asarray(eye_windows(size, face)) > 0, iterations=LID_MARGIN)
                   for face in rig.faces}
    all_windows = np.logical_or.reduce(list(own_windows.values()))

    # Repaint regions: the two blobs where the painting really differs (the old
    # bulge with the hair now lying over that cheek, and the new bulge). Inside
    # them the painting is the only source; outside nothing changes.
    delta = np.abs(source.astype(int) - ref.astype(int)).max(-1)
    core = nd.binary_opening(delta > 30, iterations=2) & zones
    blob = nd.binary_closing(nd.binary_dilation(core, iterations=5), iterations=8)
    labels, _ = nd.label(blob)
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    region = nd.binary_fill_holes(np.isin(labels, np.flatnonzero(sizes >= 1500))) & zones
    # The left plate carries a synthetic blush on both cheeks (tools/v3_face_features
    # complete_face_plate). Take both blush areas whole from the painting, otherwise
    # the two blush tones meet inside the cheek.
    yy, xx = np.indices(region.shape)
    for cx, cy, rx, ry in ((366, 593, 73, 65), (674, 558, 65, 57)):
        region |= ((xx - cx) / (rx * 1.25)) ** 2 + ((yy - cy) / (ry * 1.25)) ** 2 < 1
    region &= zones
    # Skin just outside a region but inside the painted face is repainted too: each
    # source drawing has the old outline a few pixels off, and none of them may
    # survive inside the new cheek.
    skin_region = region | (nd.binary_dilation(region, iterations=16) & nd.binary_erosion(new_skin, iterations=2) & zones)
    plate_region = nd.binary_dilation(region, iterations=16) & zones
    wide = nd.binary_dilation(region, iterations=34)
    # The painting shows the smug eyes; the skin slices and the plate must stay
    # featureless. ``clean_source`` is the painting with every eye pixel (ink, iris,
    # white of the eye; the window polygons are tight, lashes reach past them)
    # replaced by nearby skin.
    c = source.astype(int)
    skin_like = (c[..., 0] > 225) & (c[..., 1] > 130) & (c[..., 0] - c[..., 1] > 10) & (c[..., 2] > c[..., 1] - 12)
    eye_zone = nd.binary_dilation(eyes, iterations=14)
    # Not limited to the skin flood: an eye touching the fringe is not a closed hole of it.
    yy_, xx_ = np.indices(skin_like.shape)
    in_bulge = ((xx_ - BULGE[0]) / BULGE[2]) ** 2 + ((yy_ - BULGE[1]) / BULGE[3]) ** 2 <= 1
    eye_content = eye_zone & ~skin_like & ~in_bulge
    eye_content = nd.binary_dilation(eye_content, iterations=1) & ~in_bulge
    clean_source = smooth_fill(source, skin_like & new_skin & ~eye_content, eye_content)

    # 1. Skin slices: head_skin (smug original) and the clean base share one box.
    #    Alpha is the painted skin and its own outline only, never hair.
    spec = {"source": SOURCE.as_posix(), "mirror_sum": mirror_sum}
    soft = nd.gaussian_filter(new_vis.astype(np.float32), .6)
    skin_canvases = {}
    p = rig.parts["head_skin"]
    for key, image in (("head_skin", rig.images["head_skin"]), ("face_clean_base", rig.face_base)):
        a = np.asarray(on_canvas(size, image, (p["x"], p["y"]))).copy()
        # Under an unchanged eye the existing clean skin is better than a fill.
        replace = skin_region & ~(eye_content & ~region & (a[..., 3] > 0))
        a[replace, :3] = clean_source[replace]
        a[replace, 3] = np.rint(soft[replace] * 255).astype(np.uint8)
        left_a = np.asarray(on_canvas(size, image, (p["x"], p["y"])))
        back = all_windows & open_eye_colour(a) & ~open_eye_colour(left_a)
        a[back] = left_a[back]
        a[a[..., 3] == 0] = 0
        skin_canvases[key] = Image.fromarray(a)
    box = skin_canvases["head_skin"].getbbox()
    other = skin_canvases["face_clean_base"].getbbox()
    box = (min(box[0], other[0]), min(box[1], other[1]), max(box[2], other[2]), max(box[3], other[3]))
    for key, canvas in skin_canvases.items():
        canvas.crop(box).save(folder / f"{key}.png")
    spec["head_skin"] = {"file": "right/head_skin.png", "x": box[0], "y": box[1]}
    spec["face_clean_base"] = "right/face_clean_base.png"
    skin_alpha = np.asarray(skin_canvases["face_clean_base"])[..., 3]

    # 2. Clean face plate: same recipe as the left plate (opaque to 18px past the
    #    closed face, feathered to 30px), repainted only around the regions.
    plate, origin = rig.face_plate
    a = np.asarray(on_canvas(size, plate, origin)).copy()
    closed = nd.binary_fill_holes(nd.binary_closing(new_skin, iterations=18))
    alpha = np.rint(np.clip((30 - nd.distance_transform_edt(~closed)) / 12, 0, 1) * 255).astype(np.uint8)
    old_alpha = a[..., 3].copy()
    a[wide, 3] = alpha[wide]
    # Eyes with hair over a corner are not closed holes of the skin flood.
    a[eye_zone, 3] = np.maximum(old_alpha, a[..., 3])[eye_zone]
    paint = (plate_region | (wide & (old_alpha < 250))) & ~(eye_content & ~region & (old_alpha >= 250))
    paint &= a[..., 3] > 0
    # Cross-fade at the edge of the repainted area: the source drawings agree there
    # only to within a pixel or two, and a hard cut shows as a doubled line.
    blend = np.clip(nd.gaussian_filter(plate_region.astype(np.float32), 4), 0, 1)[..., None]
    mixed = np.rint(a[..., :3] * (1 - blend) + clean_source * blend).astype(np.uint8)
    soft_paint = paint & (old_alpha >= 250)
    a[soft_paint, :3] = mixed[soft_paint]
    hard_paint = paint & (old_alpha < 250)
    a[hard_paint, :3] = clean_source[hard_paint]
    left_plate = np.asarray(on_canvas(size, plate, origin))
    back = all_windows & open_eye_colour(a) & ~open_eye_colour(left_plate)
    a[back] = left_plate[back]
    a[a[..., 3] == 0] = 0
    plate_canvas = Image.fromarray(a)
    plate_box = plate_canvas.getbbox()
    plate_canvas.crop(plate_box).save(folder / "face_plate.png")
    spec["face_plate"] = {"file": "right/face_plate.png", "x": plate_box[0], "y": plate_box[1]}

    # Open-eye plates (the artwork itself for four expressions): outside the regions
    # they are untouched; inside, the repainted clean plate with that expression's own
    # eye pixels put back, except where painted hair now covers them.
    spec["expression_face_plates"] = {}
    for face, (opened, opened_origin) in rig.expression_plates.items():
        o = np.asarray(on_canvas(size, opened, opened_origin))
        oc = o[..., :3].astype(int)
        o_skin = (oc[..., 0] > 225) & (oc[..., 1] > 130) & (oc[..., 0] - oc[..., 1] > 10) & (oc[..., 2] > oc[..., 1] - 12)
        window = nd.binary_dilation(np.asarray(eye_windows(size, face)) > 0, iterations=3)
        # The whole eye footprint, including highlights that happen to be skin-coloured.
        eye_pixels = nd.binary_fill_holes(nd.binary_closing(window & ~o_skin & (o[..., 3] > 0), iterations=7))
        # Inside a really changed area only the eye itself is kept; elsewhere in the
        # window this expression's own drawing stays whole.
        # (The window polygons are tight; lashes reach a little past them.)
        # (Painted hair over an eye corner needs no clipping here: side_hair_l is drawn above the plate.)
        eye_pixels = (window & eye_pixels) | (nd.binary_dilation(window, iterations=14) & ~region)
        a = np.asarray(plate_canvas).copy()
        clean = a.copy()
        keep = ~skin_region & (o[..., 3] > 0)
        a[keep] = o[keep]
        # Each expression sheet has the outline a few pixels off the painting's.
        # Around the repainted skin, ink that only that sheet has is the old
        # outline sticking out past the new one: drop it.
        ring = nd.binary_dilation(skin_region, iterations=14) & ~skin_region & (clean[..., 3] > 0) & zones
        stray = ring & (oc.min(-1) < 150) & (clean[..., :3].astype(int).min(-1) >= 150)
        stray = nd.binary_dilation(stray, iterations=2) & ring
        a[stray] = clean[stray]
        # 带内取干净底板；边缘 JAW_FEATHER 像素内渐变（带外一个像素都不动：框外逐像素相同的约定）。
        weight = np.clip(nd.distance_transform_edt(zone_mask(a.shape[:2], (JAW_BAND,))) / JAW_FEATHER, 0, 1)
        weight = np.where(clean[..., 3] > 0, weight, 0)[..., None]
        a[..., :3] = np.rint(a[..., :3] * (1 - weight) + clean[..., :3] * weight).astype(np.uint8)
        put = eye_pixels & (o[..., 3] > 0)
        a[put, :3] = o[put][:, :3]
        back = own_windows[face] & open_eye_colour(a) & ~open_eye_colour(o)
        a[back] = o[back]
        a[a[..., 3] == 0] = 0
        file = f"right/plate_{face}_open.png"
        Image.fromarray(a).crop(plate_box).save(path.parent / file)
        spec["expression_face_plates"][face] = {"open": file, "x": plate_box[0], "y": plate_box[1]}

    # Eye slices and the fringe mask stay the left rig's: nothing in an eye window comes from the painting.

    # 3. Hair: every head layer below the plate loses its pixels inside the regions;
    #    the painted hair there goes to the side hair of that side, so it sways with it.
    from v3proto.render import BODY, LEGS
    above = ("ribbon", "flower", "ahoge")
    body = Image.new("RGBA", size)
    above_alpha = np.zeros(size[::-1], bool)
    for name in rig.order:
        q = rig.parts[name]
        if name in BODY | LEGS:
            body.alpha_composite(rig.images[name], (q["x"], q["y"]))
        if name in above:
            above_alpha |= np.asarray(on_canvas(size, rig.images[name], (q["x"], q["y"])))[..., 3] > 128
    body = np.asarray(body)
    body_like = (body[..., 3] > 128) & (np.abs(body[..., :3].astype(int) - source.astype(int)).max(-1) < 45)
    fill = region & ~new_vis & ~white & ~body_like & ~above_alpha
    old_masks = [entry["mask"] for entry in rig.cheek_images.values()]
    spec["layers"], spec["face_hair_clean"] = {}, {}
    targets = {"side_hair_l": left_zone, "side_hair_r": right_zone}
    names = [n for n in head_layer_names(rig) if n != "head_skin" and n not in above]
    names += [n for n in ("head_under", "back_hair_under") if n in rig.parts]
    for name in names:
        q = rig.parts[name]
        for store, key in ((rig.images, "layers"), (rig.face_hair_images, "face_hair_clean")):
            if name not in store:
                continue
            before = store[name]
            image = before if rig.parts[name]["source"] == "gpt_underlay" else \
                cut_old_cheek(before, (q["x"], q["y"]), rig.cheek_config, old_masks)
            a = np.asarray(on_canvas(size, image, (q["x"], q["y"]))).copy()
            a[region] = 0
            if key == "layers" and name in targets:
                mine = fill & targets[name]
                a[mine, :3] = source[mine]
                a[mine, 3] = 255
            canvas = Image.fromarray(a)
            # Keep the vertical extent: side-hair sway is measured from the slice's bottom edge.
            content = canvas.getbbox() or (q["x"], q["y"], q["x"] + 1, q["y"] + 1)
            layer_box = (min(q["x"], content[0]), q["y"], max(q["x"] + before.width, content[2]), q["y"] + before.height)
            if content[1] < layer_box[1] or content[3] > layer_box[3]:
                raise ValueError("painted hair leaves the vertical range of " + name)
            result = canvas.crop(layer_box)
            if key == "face_hair_clean":
                if layer_box[0] != q["x"] or result.size != before.size:
                    raise ValueError("face-clean hair must keep its box: " + name)
                if result.tobytes() != before.tobytes():
                    file = f"right/{name}_face_clean.png"
                    result.save(path.parent / file)
                    spec[key][name] = file
            elif layer_box[0] != q["x"] or result.size != before.size or result.tobytes() != before.tobytes():
                file = f"right/{name}.png"
                result.save(path.parent / file)
                spec[key][name] = {"file": file, "x": layer_box[0], "y": layer_box[1]}


    # 4. Cheek interaction. The motion math is the left cheek's, reflected about
    #    mirror_sum and shifted by dy (the painted bulge sits a little higher);
    #    the assets themselves are cut straight from the painted plate.
    spec["cheek"] = {"box": [BOX[0], BOX[1] + dy, BOX[2], BOX[3] + dy],
                     "vertical": [v + dy for v in REGION["vertical"]],
                     "cap_x": REGION["cap_x"], "root_x": REGION["root_x"]}
    data = json.loads(path.read_text(encoding="utf-8"))
    data["right_side"] = spec
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    right = Rig(path, cheek_side="right")

    cheek_box = mirrored_box(spec["cheek"], mirror_sum)
    faces = {}
    clean_plate = on_canvas(size, *right.face_plate)
    for face in right.faces:
        plate, origin = plate_face(right, face, 1)
        mask, texture, hit = right_face_assets(on_canvas(size, plate, origin), clean_plate,
                                               eye_windows(size, face), cheek_box, mirror_sum, dy)
        prefix = f"right/cheek_{face}"
        mask.save(path.parent / (prefix + "_mask.png"))
        texture.save(path.parent / (prefix + ".png"))
        hit.save(path.parent / (prefix + "_hit.png"))
        if not hit.getbbox():
            raise ValueError("empty right cheek hit area: " + face)
        faces[face] = {"mask": prefix + "_mask.png", "texture": prefix + ".png", "hit": prefix + "_hit.png"}
    spec["cheek"]["faces"] = faces
    # What shows behind the bulge while it is pulled away: the original artwork's
    # ordinary right cheek and the hair lock over it (head layers only, no features).
    under = Image.new("RGBA", size)
    for name in head_layer_names(rig):
        q = rig.parts[name]
        image = rig.face_base if name == "head_skin" else rig.face_hair_images.get(name, rig.images[name])
        under.alpha_composite(image, (q["x"], q["y"]))
        if name == "bangs":
            under.alpha_composite(rig.face_plate[0], rig.face_plate[1])
    under.crop(mirrored_box(spec["cheek"], mirror_sum)).save(folder / "cheek_under.png")
    spec["cheek"]["under"] = "right/cheek_under.png"
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    report = {"mirror_sum": mirror_sum, "dy": dy, "fit_mean_abs_px": round(fit_cost, 2),
              "region_pixels": {"left": int((region & left_zone).sum()), "right": int((region & right_zone).sum())},
              "hair_fill_pixels": {"left": int((fill & left_zone).sum()), "right": int((fill & right_zone).sum())},
              "skin_patch_outside_painted_skin": int((region & (skin_alpha > 0) & ~nd.binary_dilation(new_vis, iterations=2)).sum()),
              "hair_fill_overlapping_skin": int((fill & new_vis).sum()),
              "white_inside_regions": int((region & white).sum()),
              "replaced_layers": sorted(spec["layers"]) + [n + "_face_clean" for n in spec["face_hair_clean"]],
              "head_skin_box": list(box), "plate_box": list(plate_box),
              "cheek_box": list(cheek_box)}
    out.mkdir(parents=True, exist_ok=True)
    (out / "right-plate-build.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=1))
    residual(Rig(path, cheek_side="right"), source, out)


def residual(right, source, out):
    """How far the assembled right rig is from the painting (smug, rest)."""
    image = Image.new("RGBA", right.size, "white")
    image.alpha_composite(right.rest("smug", original=True))
    got = np.asarray(image.convert("RGB")).astype(int)
    delta = np.abs(got - source.astype(int)).max(-1)
    solid = nd.binary_opening(delta > THRESHOLD, iterations=2)
    heat = np.repeat(source.mean(-1, keepdims=True) * .35 + 255 * .65, 3, -1)
    level = np.clip(delta / 160, 0, 1)[..., None]
    heat = heat * (1 - level) + np.array([220, 0, 0]) * level
    head = Image.fromarray(heat.astype(np.uint8)).crop((60, 0, 1030, 860))
    head.resize((head.width * 3 // 4, head.height * 3 // 4), Image.Resampling.LANCZOS).save(out / "right-plate-residual.png")
    print("residual vs painting: solid pixels", int(solid.sum()), "of which in zones", int((solid & zone_mask(solid.shape)).sum()))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("diff")
    d.add_argument("--out", type=Path, default=OUT)
    sub.add_parser("build")
    args = parser.parse_args(argv)
    rig = Rig(DEFAULT_RIG)
    if args.cmd == "diff":
        print(json.dumps(diff_report(reference(rig), load_source(rig), args.out), indent=1))
    else:
        build(rig)


if __name__ == "__main__":
    main()
