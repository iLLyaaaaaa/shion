"""用 V3 预渲染图生成周报立绘：assets/weekly/*.png（透明底、静态、裁到可见范围）。

python -m tools.v3_weekly_sprites [--output-dir assets/weekly]

站姿用 v3proto.render.Rig.rest(表情)；collapse 用 scene 图的角色层。
文件名即 assets/weekly_titles.json 里的 sprite 键。
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SPRITE_HEIGHT = 860  # 周报里的位置高 430 逻辑像素，留 2 倍给高分屏

# 周报立绘名 -> 站姿表情（collapse 另走 scene）
STANDING = {"idle": "neutral", "happy": "happy", "done": "happy", "cheer": "happy",
            "yawn": "yawn", "slump": "tired"}
SCENES = ROOT / "assets" / "sprites" / "v3" / "scenes"


def fit(image: Image.Image) -> Image.Image:
    image = image.crop(image.getbbox())
    width = max(1, round(image.width * SPRITE_HEIGHT / image.height))
    return image.resize((width, SPRITE_HEIGHT), Image.Resampling.LANCZOS)


def collapse_image() -> Image.Image:
    scene = Image.open(SCENES / "collapse.png").convert("RGBA")
    mask = Image.open(SCENES / "collapse_char.png").convert("L")
    alpha = Image.composite(scene.getchannel("A"), Image.new("L", scene.size, 0), mask)
    scene.putalpha(alpha)
    return scene


def generate(output: Path) -> list[Path]:
    from v3proto.render import Rig
    rig = Rig()
    output.mkdir(parents=True, exist_ok=True)
    cache: dict[str, Image.Image] = {}
    written = []
    for name, face in STANDING.items():
        if face not in cache:
            cache[face] = fit(rig.rest(face))
        path = output / f"{name}.png"
        cache[face].save(path, compress_level=9)
        written.append(path)
    path = output / "collapse.png"
    fit(collapse_image()).save(path, compress_level=9)
    written.append(path)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "assets/weekly")
    args = parser.parse_args()
    for path in generate(args.output_dir):
        print(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)


if __name__ == "__main__":
    main()
