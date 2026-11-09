"""Right-side cheek: mirror the face skin about the eye midline.

Only the skin plates (head_skin, the clean face plate) and the cheek interaction
assets are flipped. Hair, bangs, flower, ribbon, eyes, mouth and body keep their
original pixels. Reference pixel ``i`` maps to ``mirror_sum - i``; the default sum
puts the axis on the midpoint between the two eyes.
"""
import numpy as np
from PIL import Image, ImageChops, ImageOps

EYE_MIDLINE_SUM = 1041


def flipped_origin(mirror_sum, x, width):
    return mirror_sum - (x + width - 1)


def mirror_canvas(image, mirror_sum):
    """Flip a canvas-sized image so that pixel i lands on mirror_sum - i."""
    out = Image.new(image.mode, image.size, 0)
    out.paste(ImageOps.mirror(image), (mirror_sum - (image.width - 1), 0))
    return out


def head_layer_names(rig):
    from .render import BODY, LEGS
    return [n for n in rig.active('smug') if n not in BODY | LEGS
            and rig.parts[n]['source'] != 'gpt_underlay' and not rig.parts[n].get('role')]


def cut_old_cheek(image, origin, config, masks):
    """Remove every pixel the original left cheek owns (union over expressions)."""
    box = config['box']
    union = Image.new('L', image.size)
    for mask in masks:
        layer = Image.new('L', image.size)
        layer.paste(mask, (box[0] - origin[0], box[1] - origin[1]))
        union = ImageChops.lighter(union, layer)
    clear = np.asarray(union) > 0
    yy, xx = np.indices(clear.shape)
    xx = xx + origin[0]
    yy = yy + origin[1]
    clear &= (xx < config['root_x'] - 4) & (yy > config['vertical'][0] + 2) & (yy < config['vertical'][-1] - 2)
    a = np.asarray(image).copy()
    a[clear] = 0
    return Image.fromarray(a)


def apply_cheek_side(rig, side, mirror_sum=EYE_MIDLINE_SUM):
    """Mutate a freshly loaded rig so that the bulging cheek is on ``side``."""
    if side == 'left':
        rig.mirror_sum = None
        return rig
    if side != 'right':
        raise ValueError('cheek side must be left or right')
    if not rig.cheek_config:
        raise ValueError('rig has no cheek interaction to mirror')
    config = rig.cheek_config
    rig.mirror_sum = mirror_sum
    # Keep the pristine left-side assets: they still define what the old cheek
    # owned in hair slices and which hidden hair to reveal there.
    rig.left_cheek_images = rig.cheek_images
    old_masks = [entry['mask'] for entry in rig.cheek_images.values()]
    for name in head_layer_names(rig):
        if name == 'head_skin':
            continue
        p = rig.parts[name]
        rig.images[name] = cut_old_cheek(rig.images[name], (p['x'], p['y']), config, old_masks)
        if name in rig.face_hair_images:
            rig.face_hair_images[name] = cut_old_cheek(rig.face_hair_images[name], (p['x'], p['y']), config, old_masks)
    # Skin: the head_skin slice and the clean face plate.
    p = rig.parts['head_skin']
    skin = rig.images['head_skin']
    rig.face_base = ImageOps.mirror(rig.face_base)
    rig.images['head_skin'] = ImageOps.mirror(skin)
    p['x'] = flipped_origin(mirror_sum, p['x'], skin.width)
    if rig.face_plate:
        plate, (px, py) = rig.face_plate
        rig.face_plate = (ImageOps.mirror(plate), (flipped_origin(mirror_sum, px, plate.width), py))
    # Cheek interaction assets live in the mirrored frame; the motion math in
    # config stays in left-side space and is mirrored by Cheek.
    mirrored = {}
    for face, assets in rig.cheek_images.items():
        mirrored[face] = {k: (mirror_canvas(v, mirror_sum) if k == 'protect' else ImageOps.mirror(v))
                          for k, v in assets.items()}
    # Every expression's cheek texture is cut from the mirrored clean face plate
    # itself: same source as the skin underneath, so pinch and rest cannot disagree.
    plate, (px, py) = rig.face_plate
    x0, y0, x1, y1 = mirrored_box(config, mirror_sum)
    crop = plate.crop((x0 - px, y0 - py, x1 - px, y1 - py))
    for assets in mirrored.values():
        keep = np.asarray(assets['texture'])[..., 3] > 0
        a = np.asarray(crop).copy()
        a[~keep] = 0
        assets['texture'] = Image.fromarray(a)
    rig.cheek_images = mirrored
    # Draw order: the bulge covers the hair on its own side.
    layers = list(rig.data['layers'])
    i, j = layers.index('side_hair_l'), layers.index('side_hair_r')
    layers[i], layers[j] = layers[j], layers[i]
    rig.data['layers'] = layers
    rig.order = sorted(rig.parts, key=lambda n: layers.index(rig.parts[n]['layer']))
    rig._blink_regions = {}
    rig._mirror_opened = {}
    return rig


def fringe_keep(rig, size, origin, margin=24):
    """255 where original-side fringe pixels may still be restored, 0 around the
    mirrored cheek zone (feathered)."""
    from scipy import ndimage as nd
    cache = rig.__dict__.setdefault('_fringe_keep', {})
    if size not in cache:
        x0, y0, x1, y1 = mirrored_box(rig.cheek_config, rig.mirror_sum)
        blocked = np.zeros(size[::-1], bool)
        blocked[max(0, y0 - margin - origin[1]):max(0, y1 + margin - origin[1]),
                max(0, x0 - margin - origin[0]):max(0, x1 + margin - origin[0])] = True
        keep = 1 - np.clip(nd.gaussian_filter(blocked.astype(np.float32), 6) * 1.5, 0, 1)
        cache[size] = Image.fromarray((keep * 255).astype(np.uint8))
    return cache[size]


def mirrored_box(config, mirror_sum):
    x0, y0, x1, y1 = config['box']
    return (mirror_sum - (x1 - 1), y0, mirror_sum - x0 + 1, y1)
