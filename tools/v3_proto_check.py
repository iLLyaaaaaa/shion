"""Deterministic preview screenshots, never opens source artwork in a viewer.

Run: python -m tools.v3_proto_check
"""
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from v3proto.animation import Pose, Settings, SWAY_PARTS
from v3proto.animation import Animator
from v3proto.__main__ import save_snapshot
from v3proto.render import Renderer, Rig


def contact(tiles, output, columns=4):
    w, h = tiles[0][1].size
    canvas = Image.new("RGB", (columns * w, ((len(tiles) + columns - 1) // columns) * (h + 24)), "#ddd8d3")
    draw = ImageDraw.Draw(canvas)
    for i, (label, image) in enumerate(tiles):
        x, y = i % columns * w, i // columns * (h + 24)
        canvas.paste(image.convert("RGB"), (x, y + 24))
        draw.text((x + 8, y + 5), label, fill="black")
    canvas.save(output)


def main():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    rig = Rig()
    output = Path("build/v3/step1")
    output.mkdir(parents=True, exist_ok=True)
    renderer = Renderer(rig, 0.6)
    for label, eye_scale in (("open", 1), ("half", 0.55), ("closed", 0.1)):
        tiles = []
        for face in rig.faces:
            path = output / f"{label}-{face}.png"
            save_snapshot(renderer, Settings(expression=face), Pose(eye_scale=eye_scale), path)
            with Image.open(path) as im:
                crop = im.crop(tuple(round(v * .6) for v in (230, 320, 850, 680)))
            tiles.append((f"{face} / {label}", crop))
        contact(tiles, output / f"faces-{label}.png")
    scenarios = {
        "sway-left": (Settings(), Pose(body_scale=1.012, head_y=-4.7, angles={n: -3 for n in SWAY_PARTS})),
        "sway-right": (Settings(), Pose(body_scale=1.012, head_y=-4.7, angles={n: 3 for n in SWAY_PARTS})),
        "pinch-default": (Settings(), Pose(pinch_center=(325, 610), pinch_delta=(-120, 0))),
        "pinch-max": (Settings(pinch_maximum=200, pinch_radius=60), Pose(pinch_center=(325, 610), pinch_delta=(-200, 0))),
        "pinch-wide": (Settings(pinch_maximum=200, pinch_radius=160), Pose(pinch_center=(325, 610), pinch_delta=(-200, 24))),
        "rebound": (Settings(), Pose(pinch_center=(325, 610), pinch_delta=(44, 0))),
    }
    renderer = Renderer(rig, 0.4)
    tiles = []
    for label, (settings, pose) in scenarios.items():
        for bg_name, bg in (("light", "white"), ("dark", "#20202b")):
            path = output / f"{label}-{bg_name}.png"
            save_snapshot(renderer, settings, pose, path, bg)
            with Image.open(path) as im:
                tiles.append((f"{label} / {bg_name}", im.copy()))
    contact(tiles, output / "motion-contact.png")
    review=Path('build/v3/visual-fix')
    review.mkdir(parents=True,exist_ok=True)
    for mode in ('moving','closed','left','right'):
        tiles=[]
        for face in ('neutral','surprised','teary','angry'):
            settings=Settings(expression=face)
            pose=Animator(settings).advance(1.75)
            if mode=='closed':pose.eye_scale=.1
            if mode in ('left','right'):
                pose.angles={n:(-3 if mode=='left' else 3) for n in SWAY_PARTS}
            path=review/f'{face}-{mode}.png'
            save_snapshot(renderer,settings,pose,path,'#eee9e5')
            with Image.open(path) as im:tiles.append((face,im.copy()))
        contact(tiles,review/f'review-{mode}.png')
    save_snapshot(Renderer(rig, 1), Settings(), Pose(), output / "rest.png")
    with Image.open(output / "smug-baseline.png") as a, Image.open(output / "rest.png") as b:
        expected=a.convert('RGBA')
        if rig.pink_cleanup is not None:expected.alpha_composite(rig.pink_cleanup)
        diff = np.abs(np.asarray(expected.convert("RGB")).astype(int) - np.asarray(b.convert("RGB")).astype(int))
    report = {"static_max_channel_difference": int(diff.max()), "static_changed_pixels": int((diff.max(-1) > 0).sum()),
              "screenshots": 3 * len(rig.faces) + 2 * len(scenarios) + 1 + 16,
              "contact_sheets": 8}
    (output / "snapshot-check.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
