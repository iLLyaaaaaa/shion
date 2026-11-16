"""V3 姿势变体（scene）的 Qt 部分：三张图的 QImage、点穿的家具覆盖窗。

纯逻辑和分层规则见 shion/v3_scene.py。家具画在这个覆盖窗里（做法同 shion/effects.py 的
SleepZOverlay：诗音窗口的附属顶层窗口，完全点穿、不抢焦点）；诗音窗口自己的遮罩只含角色，
所以点到家具会穿到下面的桌面。
"""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QWidget

from shion.effects import Z_BASE_HEIGHT, Z_ORIGIN, Z_OVERLAY_SIZE, SleepZOverlay
from shion.v3_scene import Scene


def _rgba_image(a: np.ndarray) -> QImage:
    a = np.ascontiguousarray(a)
    return QImage(a.data, a.shape[1], a.shape[0], a.strides[0], QImage.Format.Format_RGBA8888_Premultiplied).copy()


def _alpha_image(a: np.ndarray) -> QImage:
    a = np.ascontiguousarray(a)
    return QImage(a.data, a.shape[1], a.shape[0], a.strides[0], QImage.Format.Format_Alpha8).copy()


class SceneImages:
    """一个 scene 在某个纹理比例下的全部图像（主线程用）。

    under：垫底，只有家具颜色（没有家具时为 None）；char：只有角色，变形；furniture：家具层（覆盖窗用）；
    seam：under 的 alpha（只用来建遮罩）；alpha：角色 alpha（命中用）。
    左上角在 scene 坐标里是 (-pad, -pad)。
    """

    def __init__(self, scene: Scene, arrays: dict, dpr: float):
        self.scene = scene
        self.scale = arrays["scale"]          # 数组像素 / rig 像素
        self.pad = arrays["pad"]
        self.size = arrays["size"]            # 数组宽高（设备像素）
        self.dpr = dpr
        self.under = _rgba_image(arrays["under"]) if arrays["under"] is not None else None
        self.char = _rgba_image(arrays["char"])
        self.furniture = _rgba_image(arrays["furniture"]) if scene.has_furniture else None
        self.seam = _alpha_image(arrays["seam"]) if arrays["seam"].any() else None
        self.alpha = arrays["alpha"]

    @property
    def rig_size(self) -> tuple[float, float]:
        """图像（含留边）占的 scene/rig 像素宽高。"""
        return self.size[0] / self.scale, self.size[1] / self.scale

    def nbytes(self) -> int:
        total = self.alpha.nbytes
        for image in (self.under, self.char, self.furniture, self.seam):
            if image is not None:
                total += image.sizeInBytes()
        return total


class SceneOverlay(QWidget):
    """家具覆盖窗：完全点穿，只画家具层。位置由诗音窗口按当前 scene 算好后给它：
    rect 是家具图在全局坐标里的精确矩形（逻辑像素，可能带小数）；窗口取整，图像按小数偏移画，
    这样和诗音窗口里垫底的整图在同一个亚像素位置，边上不会差出一条缝。"""

    def __init__(self, pet):
        super().__init__(pet)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowTransparentForInput
                            | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.pet = pet
        self.image: QImage | None = None
        self.opacity = 1.0
        self._rect = QRectF()
        self._topmost = False

    def image_rect(self) -> QRectF:
        """图像在覆盖窗自己坐标里的矩形。"""
        return QRectF(self._rect).translated(-self.x(), -self.y())

    def set_scene(self, image: QImage | None, rect: QRectF | None, opacity: float, topmost: bool) -> None:
        changed = image is not self.image or abs(opacity - self.opacity) > 1e-4
        self.image, self.opacity = image, opacity
        if rect is not None and rect != self._rect:
            self._rect = QRectF(rect)
            x, y = math.floor(rect.left()), math.floor(rect.top())
            w, h = math.ceil(rect.right()) - x, math.ceil(rect.bottom()) - y
            if (self.x(), self.y(), self.width(), self.height()) != (x, y, w, h):
                self.setFixedSize(w, h)
                self.move(x, y)
            changed = True
        if topmost != self._topmost:
            from shion.windowing import set_topmost
            set_topmost(self, topmost)
            self._topmost = topmost
        visible = image is not None and opacity > 0 and self.pet.isVisible()
        if visible != self.isVisible():
            self.setVisible(visible)
            changed = True
        if changed and visible:
            self.update()

    def paintEvent(self, _event) -> None:
        if self.image is None:
            return
        p = QPainter(self)
        p.setRenderHints(QPainter.SmoothPixmapTransform)
        p.setOpacity(self.opacity)
        p.drawImage(self.image_rect(), self.image)
        p.end()


class V3SleepZ(SleepZOverlay):
    """睡觉的 Z：窗口给出 scene 里的出 Z 点（v3_sleep_z_anchor）时用它，否则走 V2 的锚点。"""

    def follow(self) -> None:
        anchor = self.pet.v3_sleep_z_anchor(self.state)
        if anchor is None:
            super().follow()
            return
        self.scale = self.pet.sprite_height / Z_BASE_HEIGHT
        size = math.ceil(Z_OVERLAY_SIZE * self.scale)
        self.setFixedSize(size, size)
        self.move(anchor.x() - round(Z_ORIGIN[0] * self.scale), anchor.y() - round(Z_ORIGIN[1] * self.scale))


def local_origin(win, scene: Scene, scale_logical: float, pad: float) -> QPointF:
    """scene 图左上角（含留边）在诗音窗口坐标里的位置（逻辑像素），静止、不含 V2 压扁/跳跃。

    与 V3PetWindow._draw_sprite 画站姿的换算一致：窗口水平中心 = 脚底中心 = scene 的 anchor_x，
    窗口底边上方 MARGIN_BOTTOM + gap = scene 的地面线。
    """
    from shion.pet_window import MARGIN_BOTTOM
    from shion.v3_display import V2_FOOT_GAP_RATIO
    gap = win._height * V2_FOOT_GAP_RATIO
    return QPointF(win.width() / 2 - (pad + scene.anchor_x) * scale_logical,
                   win.height() - MARGIN_BOTTOM - gap - (pad + scene.ground_y) * scale_logical)


__all__ = ["SceneImages", "SceneOverlay", "V3SleepZ", "local_origin", "QPoint"]
