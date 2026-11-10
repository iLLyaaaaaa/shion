"""S6：给 GPT 新画素材用的参考合成图（需新画清单见 docs/v3-integration-plan.md）。

用法：
  python -m tools.v3_art_refs refs [--out build/v3/art-refs]
      生成全部参考图和 refs.json（每张图的尺寸、对应 rig 坐标的裁切框、放大倍数）。
  python -m tools.v3_art_refs pad <输入> <输出> [--size 1086x1448]
      GPT 输出尺寸不对时：等比缩放到能放进目标尺寸，再用白边补齐（居中）。

参考图都是白底、无动画、rig 画布坐标（1086×1448 = ref.png 像素）。只读 assets/sprites/v3，
不碰 raw。裁切图的 rig 坐标 = 裁切框左上角 + 图内像素 / 放大倍数。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

# 裁切框：rig 坐标 (x0, y0, x1, y1)
HEAD_BOX = (90, 0, 1000, 760)      # 整个头：呆毛顶 y≈13、花饰、鬓发、鼓脸颊都在内（实测 x 105..988）
ARMS_BOX = (150, 700, 940, 1010)   # 双臂和手：arm_l (191..484) + arm_r (657..889)
ZOOM = 2


def _white(image: Image.Image) -> Image.Image:
    bg = Image.new("RGBA", image.size, "white")
    bg.alpha_composite(image)
    return bg.convert("RGB")


def _crop(image: Image.Image, box, zoom=ZOOM) -> Image.Image:
    part = image.crop(box)
    return part.resize((part.width * zoom, part.height * zoom), Image.Resampling.LANCZOS)


def build(out: Path) -> dict:
    from v3proto.render import Rig
    rig = Rig()
    w, h = rig.size
    smug = _white(rig.rest("smug", original=True))  # tools/v3_replace_expressions 对位用的就是这张
    neutral = _white(rig.rest("neutral"))
    sleep = _white(rig.rest("sleep"))
    wide = Image.new("RGB", (w * 2, h), "white")
    wide.paste(neutral, (w // 2, 0))
    images = {
        # 1 working 道具
        "working-full.png": (neutral, None, 1, "neutral 全身；道具零件图另画，这张用来对位"),
        "arms-x2.png": (_crop(neutral, ARMS_BOX), ARMS_BOX, ZOOM, "双臂区域放大：working 拿道具、stop 挡手"),
        # 2 右鼓版脸部底板
        "full-left-ref.png": (smug, None, 1, "当前左鼓原图（smug，S0 定稿）"),
        "head-left-ref.png": (_crop(smug, HEAD_BOX), HEAD_BOX, ZOOM, "左鼓头部放大：右鼓版按此整张重画，只把鼓脸颊换到画面右侧"),
        # 3/4 姿势、家具
        "pose-full.png": (neutral, None, 1, "站姿全身：collapse 坐倒、desk 趴桌、bed 躺姿的比例参考"),
        "scene-wide.png": (wide, (-w // 2, 0, w + w // 2, h), 1, "左右各扩 50%：给书桌、床留位置"),
        # 表情（3/6/7）
        "face-smug-ref.png": (smug, None, 1, "表情输入的底图：新表情须同画布、同姿势，只改五官"),
        "face-neutral.png": (neutral, None, 1, "neutral 表情参考（slump、neglect1）"),
        "face-sleep.png": (sleep, None, 1, "sleep 表情参考（yawn）"),
    }
    out.mkdir(parents=True, exist_ok=True)
    meta = {"canvas": [w, h], "background": "#FFFFFF", "images": {}}
    for name, (image, box, zoom, note) in images.items():
        image.save(out / name)
        meta["images"][name] = {"size": list(image.size), "rig_box": list(box or (0, 0, w, h)),
                                "zoom": zoom, "note": note}
    (out / "refs.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def pad(src: Path, dst: Path, size=(1086, 1448)) -> Image.Image:
    with Image.open(src) as im:
        image = im.convert("RGBA")
    k = min(size[0] / image.width, size[1] / image.height)
    image = image.resize((round(image.width * k), round(image.height * k)), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", size, "white")
    canvas.alpha_composite(image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2))
    result = canvas.convert("RGB")
    dst.parent.mkdir(parents=True, exist_ok=True)
    result.save(dst)
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("refs")
    r.add_argument("--out", type=Path, default=Path("build/v3/art-refs"))
    q = sub.add_parser("pad")
    q.add_argument("src", type=Path)
    q.add_argument("dst", type=Path)
    q.add_argument("--size", default="1086x1448")
    a = p.parse_args(argv)
    if a.cmd == "refs":
        meta = build(a.out)
        for name, info in meta["images"].items():
            print(f"{name:20s} {info['size'][0]}x{info['size'][1]}  {info['note']}")
    else:
        w, h = (int(v) for v in a.size.lower().split("x"))
        pad(a.src, a.dst, (w, h))


if __name__ == "__main__":
    main()
