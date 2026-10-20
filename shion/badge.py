"""停下标记：hook 真的在检查点停住后，诗音头顶旁边一直显示的小 ⏸。

独立的小窗口（不是气泡）：气泡换句、被盖掉都不影响它；鼠标点穿，不抢焦点。
图案用 QPainter 画两根竖条，不依赖字体里有没有 ⏸ 字形。
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QWidget

BADGE_RATIO = 0.055  # 标记边长 / 精灵高度
BADGE_MIN = 18
BADGE_MAX = 30
BADGE_X = 0.76  # 标记中心在精灵本体宽度上的位置（头顶右侧，避开头顶正上方的气泡）
BADGE_Y = 0.05  # 标记中心在精灵本体高度上的位置
BG = QColor(10, 10, 10, 220)
BORDER = QColor(245, 130, 54)
BARS = QColor(252, 242, 230)


def badge_size(sprite_height: int) -> int:
    return max(BADGE_MIN, min(BADGE_MAX, round(sprite_height * BADGE_RATIO)))


def badge_geometry(
    body: tuple[int, int, int, int],
    size: int,
    avail: tuple[int, int, int, int],
    jump_offset: float = 0.0,
) -> tuple[int, int]:
    """返回标记左上角（屏幕坐标）。body：精灵本体 (x, y, w, h)；跳起时跟着上移；夹进可用区域。"""
    bx, by, bw, bh = body
    ax, ay, aw, ah = avail
    x = round(bx + bw * BADGE_X - size / 2)
    y = round(by + bh * BADGE_Y - size / 2 - jump_offset)
    return max(ax, min(x, ax + aw - size)), max(ay, min(y, ay + ah - size))


def paint_badge(p: QPainter, size: int) -> None:
    p.setRenderHint(QPainter.Antialiasing)
    r = QRectF(0.75, 0.75, size - 1.5, size - 1.5)
    p.setPen(BORDER)
    p.setBrush(BG)
    p.drawRoundedRect(r, size * 0.28, size * 0.28)
    p.setPen(Qt.NoPen)
    p.setBrush(BARS)
    bar_w, bar_h = size * 0.16, size * 0.46
    top = (size - bar_h) / 2
    for cx in (size * 0.37, size * 0.63):
        p.drawRoundedRect(QRectF(cx - bar_w / 2, top, bar_w, bar_h), bar_w * 0.35, bar_w * 0.35)


def render_badge(size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    paint_badge(p, size)
    p.end()
    return img


class PauseBadge(QWidget):
    def __init__(self, pet):
        super().__init__(pet, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.NoFocus)
        self.pet = pet
        self.wanted = False  # 控制器要求显示（宠物窗口隐藏时先不显示，重新显示时恢复）
        self.resize_to(pet.sprite_height)
        pet.moved.connect(self.follow)

    def resize_to(self, sprite_height: int) -> None:
        s = badge_size(sprite_height)
        self.setFixedSize(s, s)

    def set_wanted(self, on: bool) -> None:
        self.wanted = on
        self.refresh()

    def refresh(self) -> None:
        if self.wanted and self.pet.isVisible():
            self.follow()
            if not self.isVisible():
                self.show()
                self.raise_()
        elif self.isVisible():
            self.hide()

    def follow(self) -> None:
        if not self.wanted:
            return
        avail = self.pet._screen_avail(self.pet.geometry().center())
        x, y = badge_geometry(self.pet.body_rect(), self.width(),
                              (avail.x(), avail.y(), avail.width(), avail.height()), self.pet._jump_offset)
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        paint_badge(p, self.width())
        p.end()
