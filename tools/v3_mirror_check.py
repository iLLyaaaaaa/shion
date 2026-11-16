"""Left/right bulging-cheek comparison sheets (expressions x rest / pinch / lift / hair swung both ways).

python -m tools.v3_mirror_check [--out build/v3/integrate/mirror]
"""
import argparse
import os
from pathlib import Path

from PIL import Image

from tools.v3_proto_check import contact

SCALE = .5
SWAY = 4  # degrees; the idle sway is 2, impulses overshoot it


def head_crop(image, box, scale=SCALE):
    return image.crop(tuple(round(v * scale) for v in box))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('build/v3/integrate/mirror'))
    parser.add_argument('--faces', default='')
    args = parser.parse_args(argv)
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from v3proto.animation import Animator, Pose, Settings, SWAY_PARTS
    from v3proto.lift import SCENE_PADDING
    from v3proto.lift_scenarios import lift_scenario
    from v3proto.render import Renderer, Rig, to_pil
    args.out.mkdir(parents=True, exist_ok=True)
    for side in ('left', 'right'):
        rig = Rig(cheek_side=side)
        renderer = Renderer(rig, SCALE)
        faces = args.faces.split(',') if args.faces else list(rig.faces)
        # Pose describes the pull in cheek-local terms: outward is always negative x.
        dy = rig.cheek_config['box'][1] - 536
        pivot = (325., 586.) if rig.mirror_sum is None else (rig.mirror_sum - 325., 586. + dy)
        tiles = []
        for face in faces:
            settings = Settings(expression=face, pinch_maximum=200)
            views = {
                'rest': Pose(head_y=-1),
                'pinch': Pose(head_y=-1, pinch_delta=(-110., -8.)),
            }
            for label, pose in views.items():
                rgba = to_pil(renderer.render(settings, pose))
                base = Image.new('RGBA', rgba.size, '#eee9e5')
                base.alpha_composite(rgba)
                tiles.append((f'{side} / {face} / {label}', head_crop(base, (110, 300, 960, 800))))
            animator = Animator(settings, 7, star_seed=7)
            pose = lift_scenario(animator, 'held', .8, pivot)
            rgba = to_pil(renderer.render(settings, pose, padding=SCENE_PADDING))
            base = Image.new('RGBA', rgba.size, '#eee9e5')
            base.alpha_composite(rgba)
            ox, oy = pose.root_offset
            left, top = SCENE_PADDING[0], SCENE_PADDING[1]
            tiles.append((f'{side} / {face} / lift', head_crop(
                base, (110 + left + ox - 120, 300 + top + oy - 120, 960 + left + ox + 120, 800 + top + oy + 120))
                .resize((round(850 * SCALE), round(500 * SCALE)))))
            # Hair swung to its limit both ways: the hair now lying over the old
            # cheek must move as one piece with its side hair, with no second copy.
            for label, angle in (('hair -%d' % SWAY, -SWAY), ('hair +%d' % SWAY, SWAY)):
                rgba = to_pil(renderer.render(settings, Pose(head_y=-1, angles={n: angle for n in SWAY_PARTS})))
                base = Image.new('RGBA', rgba.size, '#eee9e5')
                base.alpha_composite(rgba)
                tiles.append((f'{side} / {face} / {label}', head_crop(base, (110, 300, 960, 800))))
        # Keep every tile the same size for the sheet.
        size = tiles[0][1].size
        tiles = [(label, image.resize(size, Image.Resampling.LANCZOS)) for label, image in tiles]
        contact(tiles, args.out / f'{side}-contact.png', columns=5)
        print('wrote', args.out / f'{side}-contact.png')


if __name__ == '__main__':
    main()
