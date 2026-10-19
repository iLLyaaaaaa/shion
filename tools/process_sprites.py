"""把 assets/sprites/raw/ 里 GPT 生成的原图处理成程序用的精灵图，输出到 assets/sprites/。

GPT 每次画的人物大小、画布尺寸都不一样，所以这个脚本不依赖固定坐标：
1. alpha 清理 + 去毛边（半透明边缘的颜色换成最近的不透明像素颜色）
2. 统一大小：以 idle 为基准。站立的图把人物高度缩放到和 idle 一样；
   坐着/悬空的图（SCALE_FROM_STANDING）用站立图的平均缩放比例
3. 对齐：所有图使用同样大小的画布（CANVAS），脚底贴底（留 BOTTOM 像素），
   水平方向按“头部”（人物上部 HEAD_FRAC）的重心居中，切换表情时头不会左右跳
4. 可以用 EXTRA_SCALE 对单张图手动微调大小

用法：python tools/process_sprites.py
"""
from pathlib import Path
import numpy as np
from PIL import Image
from scipy import ndimage as nd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "assets" / "sprites" / "raw"
OUT = ROOT / "assets" / "sprites"

CANVAS = (448, 512)       # 输出画布（宽, 高）
FIG_H = 480               # idle 人物在输出中的高度
BOTTOM = 8                # 脚底离画布底边的距离
HEAD_FRAC = 0.40          # 用人物上部多少比例来算头部重心
STANDING = ["idle", "blink", "happy", "proud", "stop", "dizzy", "working", "done", "neglect1"]
SCALE_FROM_STANDING = ["sleep", "drag", "neglect2"]
EXTRA_SCALE = {"neglect2": 0.82, "sleep": 1.06}  # 目测微调：让头的大小和 idle 一致


def load_clean(path: Path) -> Image.Image:
    a = np.array(Image.open(path).convert("RGBA"))
    al = a[..., 3]
    al[al < 16] = 0
    al[al >= 235] = 255
    opaque = al == 255
    semi = (al > 0) & ~opaque
    if semi.any() and opaque.any():
        _, (iy, ix) = nd.distance_transform_edt(~opaque, return_indices=True)
        a[semi, :3] = a[iy[semi], ix[semi], :3]
    a[al == 0, :3] = 0
    img = Image.fromarray(a)
    return img.crop(img.getbbox())


def save_retry(img: Image.Image, path: Path, tries: int = 5) -> None:
    """文件偶尔会被杀毒软件/同步盘短暂占用，失败就稍等重试。"""
    import time
    for i in range(tries):
        try:
            img.save(path, optimize=True)
            return
        except OSError:
            if i == tries - 1:
                raise
            time.sleep(0.5)


def head_center_x(img: Image.Image) -> float:
    a = np.array(img)[..., 3].astype(float)
    top = a[: max(1, int(img.height * HEAD_FRAC))]
    xs = np.arange(img.width)
    return float((top.sum(0) * xs).sum() / top.sum())


def main():
    imgs = {p.stem: load_clean(p) for p in RAW.glob("*.png")}
    base = FIG_H / imgs["idle"].height
    scales = {}
    for n in STANDING:
        if n in imgs:
            scales[n] = FIG_H / imgs[n].height
    # 站立图相对 idle 被 GPT 放大了多少，坐着/悬空的图按同样比例缩
    ratios = [scales[n] / base for n in scales if n != "idle"]
    avg = float(np.mean(ratios)) if ratios else 1.0
    for n in SCALE_FROM_STANDING:
        if n in imgs:
            scales[n] = base * avg
    W, H = CANVAS
    for n, img in imgs.items():
        s = scales.get(n, base) * EXTRA_SCALE.get(n, 1.0)
        fig = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
        cx = head_center_x(fig)
        x = round(W / 2 - cx)
        y = H - BOTTOM - fig.height
        canvas = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
        canvas.alpha_composite(fig, (x, y)) if x >= 0 and y >= 0 else canvas.paste(fig, (x, y), fig)
        if x < 0 or x + fig.width > W or y < 0:
            print(f"警告：{n} 超出画布（x={x}, y={y}, 宽={fig.width}, 高={fig.height}），被裁掉了一部分")
        save_retry(canvas, OUT / f"{n}.png")
        print(f"ok {n:9s} scale={s:.3f} size={fig.size}")


if __name__ == "__main__":
    main()
