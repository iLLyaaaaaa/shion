"""把 assets/sprites/raw/ 里 GPT 生成的原图处理成程序用的精灵图，输出到 assets/sprites/。

处理步骤：
1. alpha 清理：几乎透明的变全透明，几乎不透明的变全不透明
2. 去毛边：半透明边缘像素的颜色改成最近的不透明像素颜色（去掉红边）
3. 单张修正：happy 擦掉爱心；neglect2 缩小到 0.8 倍对齐比例
4. 合成 blink：只把 blink.png 的眼睛区域羽化贴到 idle.png 上，身体不抖
5. 统一裁剪到同一画框，缩放到 256x512

用法：python tools/process_sprites.py
"""
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage as nd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "assets" / "sprites" / "raw"
OUT = ROOT / "assets" / "sprites"

CROP = (327, 20, 927, 1220)    # 原图坐标下的统一画框（600x1200）
OUT_SIZE = (256, 512)
EYE_BOXES = [(540, 205, 615, 262), (632, 172, 712, 228)]  # 左眼、右眼（原图坐标）


def clean_alpha(img: Image.Image) -> Image.Image:
    a = np.array(img.convert("RGBA"))
    al = a[..., 3]
    al[al < 16] = 0
    al[al >= 235] = 255
    opaque = al == 255
    semi = (al > 0) & ~opaque
    if semi.any() and opaque.any():
        _, (iy, ix) = nd.distance_transform_edt(~opaque, return_indices=True)
        a[semi, :3] = a[iy[semi], ix[semi], :3]
    a[al == 0, :3] = 0
    return Image.fromarray(a)


def remove_floating_bits(img: Image.Image) -> Image.Image:
    """只保留最大的连通块（用来擦掉 happy 的爱心）。"""
    a = np.array(img)
    lab, n = nd.label(a[..., 3] > 0)
    if n > 1:
        sizes = nd.sum(np.ones_like(lab), lab, range(1, n + 1))
        keep = 1 + int(np.argmax(sizes))
        a[lab != keep] = 0
    return Image.fromarray(a)


def scale_about_feet(img: Image.Image, s: float) -> Image.Image:
    a = np.array(img)[..., 3]
    ys, xs = np.where(a > 128)
    cx, by = (xs.min() + xs.max()) / 2, ys.max()
    small = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    canvas = Image.new("RGBA", img.size, (0, 0, 0, 0))
    canvas.alpha_composite(small, (round(cx - cx * s), round(by - by * s)))
    return canvas


def make_blink(idle: Image.Image, blink: Image.Image) -> Image.Image:
    mask = Image.new("L", idle.size, 0)
    d = ImageDraw.Draw(mask)
    for box in EYE_BOXES:
        d.ellipse(box, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(6))
    out = idle.copy()
    out.paste(blink, (0, 0), mask)
    return out


def finish(img: Image.Image) -> Image.Image:
    return img.crop(CROP).resize(OUT_SIZE, Image.LANCZOS)


def main():
    names = sorted(p.stem for p in RAW.glob("*.png"))
    imgs = {n: clean_alpha(Image.open(RAW / f"{n}.png")) for n in names}
    if "happy" in imgs:
        imgs["happy"] = remove_floating_bits(imgs["happy"])
    if "neglect2" in imgs:
        imgs["neglect2"] = scale_about_feet(imgs["neglect2"], 0.8)
    if "idle" in imgs and "blink" in imgs:
        imgs["blink"] = make_blink(imgs["idle"], imgs["blink"])
    for n, im in imgs.items():
        finish(im).save(OUT / f"{n}.png", optimize=True)
        print("ok", n)


if __name__ == "__main__":
    main()
