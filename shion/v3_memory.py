"""V3 窗口用的 rig 省内存（S7）。

rig 里有几张“整张画布大小、但大部分是空的”图：每个表情的捏脸保护遮罩
（11 张 L，各约 1.5MB）、两张刘海遮罩、pink_cleanup（RGBA 约 6MB），以及有
face_plate 时根本用不到的 face_contour（RGBA 约 6MB）。运行时对它们只做
`crop(box)`（pink_cleanup 是整张叠加），所以换成只存有内容那一块的 SparseCanvas。
画面逐像素不变（tests/test_v3_memory.py）。原型和工具里加载的 Rig 不受影响。
"""
from __future__ import annotations

import numpy as np


class SparseCanvas:
    """只存非零那一块和它的位置；crop 结果与原图 crop 逐像素相同（画布外和空白处都是 0）。"""

    def __init__(self, image):
        self.size = image.size
        self.mode = image.mode
        a = np.asarray(image)
        nonzero = a.any(axis=-1) if a.ndim == 3 else a != 0
        rows, cols = np.nonzero(nonzero)
        if rows.size:
            box = (int(cols.min()), int(rows.min()), int(cols.max()) + 1, int(rows.max()) + 1)
        else:
            box = (0, 0, 0, 0)
        self.offset = box[:2]
        self.image = image.crop(box)

    @property
    def width(self) -> int:
        return self.size[0]

    @property
    def height(self) -> int:
        return self.size[1]

    def crop(self, box):
        from PIL import Image
        x0, y0, x1, y1 = (int(v) for v in box)
        out = Image.new(self.mode, (x1 - x0, y1 - y0))
        if self.image.width and self.image.height:
            out.paste(self.image, (self.offset[0] - x0, self.offset[1] - y0))
        return out


def placed(image):
    """(图, 位置)：给 alpha_composite 用，普通图位置是 (0, 0)。"""
    if isinstance(image, SparseCanvas):
        return image.image, image.offset
    return image, (0, 0)


def compact_rig(rig):
    for images in (rig.cheek_images, getattr(rig, "left_cheek_images", None) or {}):
        for entry in images.values():
            if "protect" in entry and not isinstance(entry["protect"], SparseCanvas):
                entry["protect"] = SparseCanvas(entry["protect"])
    for name in ("fringe_mask", "source_fringe_mask", "pink_cleanup"):
        image = getattr(rig, name, None)
        if image is not None and not isinstance(image, SparseCanvas):
            setattr(rig, name, SparseCanvas(image))
    if rig.face_plate is not None:
        rig.face_contour = None  # 两处合成都在用到它之前 continue 了
    return rig
