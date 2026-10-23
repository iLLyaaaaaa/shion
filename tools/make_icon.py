"""从现有 idle 精灵裁取头部；不修改精灵或 raw，使用已有 Pillow。"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shion.icons import ICON_SIZES

# 当前 448×512 的 idle：包含呆毛、发饰与两侧头发，止于头部下缘。
HEAD_BOX = (44, 22, 395, 286)


def generate_icons(output: Path) -> None:
    with Image.open(ROOT / "assets/sprites/idle.png") as source:
        if source.size != (448, 512):
            raise ValueError("idle 精灵尺寸已改变，请先重新确认 HEAD_BOX")
        head = source.convert("RGBA").crop(HEAD_BOX)
    output.mkdir(parents=True, exist_ok=True)
    frames = {}
    for size in ICON_SIZES:
        padding = 1 if size <= 32 else max(2, round(size * .025))
        frame = head.copy()
        frame.thumbnail((size - padding * 2, size - padding * 2), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (size, size))
        canvas.alpha_composite(frame, ((size - frame.width) // 2, (size - frame.height) // 2))
        if size <= 32:
            # 小尺寸单独锐化颜色，保留原透明度；一像素外描边强化白发轮廓。
            alpha = canvas.getchannel("A")
            canvas = canvas.convert("RGB").filter(ImageFilter.UnsharpMask(radius=.6, percent=140, threshold=3))
            canvas.putalpha(alpha)
            outline = Image.new("RGBA", canvas.size, (65, 29, 15))
            outline.putalpha(alpha.filter(ImageFilter.MaxFilter(3)).point(lambda a: round(a * .70)))
            outline.alpha_composite(canvas)
            canvas = outline
        frames[size] = canvas
        canvas.save(output / ("shion.png" if size == 256 else f"shion-{size}.png"), compress_level=9)
    # append_images 保留单独调过的 16/32 帧，而非由 256 帧重新缩小。
    frames[256].save(output / "shion.ico", sizes=[(s, s) for s in ICON_SIZES],
                     append_images=[frames[s] for s in ICON_SIZES if s != 256])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "assets/icon")
    args = parser.parse_args()
    generate_icons(args.output_dir)
    print(f"Generated PNG/ICO sizes {ICON_SIZES}: {args.output_dir}")


if __name__ == "__main__":
    main()
