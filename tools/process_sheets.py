"""把 raw/ 里的分帧图（*_sheet.png）切成单帧精灵图，输出到 assets/sprites/。

- walk_sheet.png → walk_1.png ~ walk_4.png
- jump_sheet.png → jump_1.png（下蹲）、jump_2.png（腾空）

处理方式：
1. 按连通区域把整张图切成若干帧（每帧都是一个完整的人物，相邻帧挨得很近也能切开）
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
    "drag_sheet": ("drag", "head", False),
}
# 每张分帧图应有的帧数；切出来的帧数不对时报错，避免生成错乱的动画
EXPECTED = {"walk_sheet": 8, "jump_sheet": 4, "drag_sheet": 4}
HEAD_TOP = 0.28     # 头部宽度测量范围：人物上部 28%（避开举起的手臂）
MIN_FRAME_AREA = 5000  # 像素数大于这个值的连通块才算一帧


def split_frames(img: Image.Image) -> list[tuple[Image.Image, int]]:
    """按连通区域切帧：每个大块是一帧，小碎块（发丝、汗滴等）归到离它最近的那一帧。

    GPT 画的分帧图里，相邻两帧的头发经常挨得很近，按竖直空隙切会切不开，所以按连通区域切。
    """
    import warnings
    from scipy import ndimage as nd
    warnings.filterwarnings("ignore", category=RuntimeWarning)  # 切开后留下的空标签会让重心计算除以 0，忽略即可
    a = np.array(img)
    mask = a[..., 3] > 40
    lab, n = nd.label(mask)
    if n == 0:
        return []
    sizes = nd.sum(mask, lab, range(1, n + 1))
    centers = nd.center_of_mass(mask, lab, range(1, n + 1))
    big = [i for i in range(n) if sizes[i] >= MIN_FRAME_AREA]
    big.sort(key=lambda i: centers[i][1])
    # 相邻两帧碰在一起时会连成一个大块：宽度明显超过中位数的块，在中间最细的竖线处切开
    slices = nd.find_objects(lab)
    widths = [slices[i][1].stop - slices[i][1].start for i in big]
    med = float(np.median(widths)) if widths else 0
    for i in list(big):
        sl = slices[i]
        w = sl[1].stop - sl[1].start
        if med and w > 1.6 * med:
            pieces = max(2, round(w / med))
            region = lab[sl] == i + 1
            cols = region.sum(0)
            cuts = []
            for k in range(1, pieces):
                c = int(w * k / pieces)
                lo, hi = max(1, c - int(med * 0.25)), min(w - 1, c + int(med * 0.25))
                cuts.append(lo + int(np.argmin(cols[lo:hi])))
            edges = [0] + cuts + [w]
            for j in range(pieces):
                new_label = lab.max() + 1
                sub = np.zeros_like(region)
                sub[:, edges[j]:edges[j + 1]] = region[:, edges[j]:edges[j + 1]]
                lab[sl][sub] = new_label
            big.remove(i)
    n = int(lab.max())
    sizes = nd.sum(mask, lab, range(1, n + 1))
    centers = nd.center_of_mass(mask, lab, range(1, n + 1))
    big = sorted([i for i in range(n) if sizes[i] >= MIN_FRAME_AREA], key=lambda i: centers[i][1])
    owner = {}
    for i in range(n):
        if i in big:
            owner[i] = i
        else:
            owner[i] = min(big, key=lambda b: abs(centers[b][1] - centers[i][1]))
    frames = []
    for b in big:
        keep = np.isin(lab, [i + 1 for i in range(n) if owner[i] == b])
        out = a.copy()
        out[~keep] = 0
        frame = Image.fromarray(out)
        box = frame.getbbox()
        frames.append((frame.crop(box), box[3]))  # (人物, 该帧脚底在整图中的 y)
    return frames


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
        frames = split_frames(full)
        want = EXPECTED.get(sheet)
        if want and len(frames) != want:
            raise SystemExit(f"{sheet}.png 切出了 {len(frames)} 帧，应该是 {want} 帧，请检查原图")
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
