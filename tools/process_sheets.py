"""把 raw/ 里的分帧图（*_sheet.png）切成单帧精灵图，输出到 assets/sprites/。

- walk_sheet.png → walk_1.png ~ walk_4.png
- jump_sheet.png → jump_1.png（下蹲）、jump_2.png（腾空）

处理方式：
1. 按透明的竖直空隙把整张图切成若干帧（每帧都是一个完整的人物）
2. 统一大小：按 SHEETS 里的方式（人物高度 或 头部宽度）和 idle 对比，
   同一张分帧图里的所有帧用同一个缩放比例，保证帧与帧之间大小一致
3. 对齐：画布与 process_sprites.py 相同；水平按头部重心居中；
   垂直方向：走路保留同一张图内各帧的相对高低；跳跃全部脚底贴地（升空由程序做）
4. 去毛边、alpha 清理与 process_sprites.py 相同

用法：python tools/process_sheets.py
"""
from pathlib import Path
import numpy as np
from PIL import Image

import process_sprites as ps

# 每张分帧图：(输出前缀, 缩放方式, 是否保留帧间高低差)
#   height：人物高度和 idle 一致（站立类动作，例如走路）
#   head  ：头部宽度和 idle 一致（姿势高度变化大的动作，例如下蹲、腾空）
#   跳跃的升空由程序做，所以 jump 不保留高低差，全部脚底贴地
SHEETS = {
    "walk_sheet": ("walk", "height", True),
    "jump_sheet": ("jump", "head", False),
}
HEAD_TOP = 0.28     # 头部宽度测量范围：人物上部 28%（避开举起的手臂）
MIN_GAP_W = 20      # 宽度小于这个值的块当作杂点忽略


def split_frames(img: Image.Image) -> list[tuple[int, int]]:
    a = np.array(img)[..., 3]
    cols = (a > 128).sum(0) > 0
    runs, start = [], None
    for x, c in enumerate(cols):
        if c and start is None:
            start = x
        elif not c and start is not None:
            runs.append((start, x)); start = None
    if start is not None:
        runs.append((start, len(cols)))
    return [r for r in runs if r[1] - r[0] >= MIN_GAP_W]


def head_width(img: Image.Image) -> int:
    a = np.array(img)[..., 3] > 128
    top = a[: max(1, int(img.height * HEAD_TOP))]
    return int(top.sum(1).max())


def main():
    idle = ps.load_clean(ps.RAW / "idle.png")
    idle_scale = ps.FIG_H / idle.height
    target_head = head_width(idle) * idle_scale
    W, H = ps.CANVAS
    for sheet, (prefix, mode, keep_lift) in SHEETS.items():
        path = ps.RAW / f"{sheet}.png"
        if not path.exists():
            print(f"跳过：没有 {path.name}")
            continue
        full = ps.load_clean(path)  # 已裁到整体边界
        frames = []
        for x0, x1 in split_frames(full):
            part = full.crop((x0, 0, x1, full.height))
            box = part.getbbox()
            frames.append((part.crop(box), box[3]))  # (人物, 该帧脚底在整图中的 y)
        if mode == "height":
            s = ps.FIG_H / float(np.median([f.height for f, _ in frames]))
        else:
            s = float(np.median([target_head / head_width(f) for f, _ in frames]))
        ground = max(b for _, b in frames)
        for i, (fig0, bottom) in enumerate(frames, 1):
            fig = fig0.resize((round(fig0.width * s), round(fig0.height * s)), Image.LANCZOS)
            lift = round((ground - bottom) * s) if keep_lift else 0
            x = round(W / 2 - ps.head_center_x(fig))
            y = H - ps.BOTTOM - fig.height - lift
            canvas = Image.new("RGBA", ps.CANVAS, (0, 0, 0, 0))
            canvas.paste(fig, (x, y), fig)
            if x < 0 or y < 0 or x + fig.width > W:
                print(f"警告：{prefix}_{i} 超出画布（x={x}, y={y}, 尺寸={fig.size}）")
            ps.save_retry(canvas, ps.OUT / f"{prefix}_{i}.png")
            print(f"ok {prefix}_{i} scale={s:.3f} size={fig.size} lift={lift}")


if __name__ == "__main__":
    main()
