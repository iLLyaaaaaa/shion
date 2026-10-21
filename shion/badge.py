"""检查点暂停标签：终端配色，只收左键，不抢焦点，出现后延迟解锁。"""
from __future__ import annotations

import math

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase, QFontMetricsF, QImage, QPainter, QPainterPath, QRegion
from PySide6.QtWidgets import QWidget

from shion.bubble import BG, BORDER, FG, FONT_PX, PAD_X, PAD_Y, pick_font_family
from shion.panel import ARM_DELAY
from shion.windowing import set_topmost

BADGE_X = 0.76
BADGE_Y = 0.05
CORNER_RADIUS = 4


def label_font(fallback=()) -> QFont:
    have = QFontDatabase.families()
    family = pick_font_family(have, QFontDatabase.systemFont(QFontDatabase.FixedFont).family())
    font = QFont(family)
    font.setPixelSize(FONT_PX)
    font.setStyleHint(QFont.Monospace)
    font.setFamilies([family, *(f for f in fallback if f in have and f != family)])
    return font


def badge_size(text: str, font: QFont) -> tuple[int, int]:
    metrics = QFontMetricsF(font)
    return math.ceil(metrics.horizontalAdvance(text)) + PAD_X * 2, math.ceil(metrics.height()) + PAD_Y * 2


def badge_geometry(body, size, avail, jump_offset=0.0) -> tuple[int, int]:
    """头顶右侧，随跳跃移动，按标签实际宽高夹在可用屏内。"""
    bx, by, bw, bh = body
    ax, ay, aw, ah = avail
    w, h = size
    x = round(bx + bw * BADGE_X - w / 2)
    y = round(by + bh * BADGE_Y - h / 2 - jump_offset)
    return max(ax, min(x, ax + aw - w)), max(ay, min(y, ay + ah - h))


def paint_badge(p: QPainter, size, text: str, font: QFont) -> None:
    w, h = size
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(BORDER)
    p.setBrush(BG)
    p.drawRoundedRect(QRectF(.5, .5, w - 1, h - 1), CORNER_RADIUS, CORNER_RADIUS)
    p.setPen(FG)
    p.setFont(font)
    p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, text)


def render_badge(text: str, font: QFont) -> QImage:
    size = badge_size(text, font)
    img = QImage(*size, QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    paint_badge(p, size, text, font)
    p.end()
    return img


class PauseBadge(QWidget):
    activated = Signal()

    def __init__(self, pet):
        super().__init__(pet, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        set_topmost(self, bool(pet.windowFlags() & Qt.WindowStaysOnTopHint))
        self.setFocusPolicy(Qt.NoFocus)
        self.setContextMenuPolicy(Qt.PreventContextMenu)
        self.setCursor(Qt.PointingHandCursor)
        self.pet = pet
        self._clock = pet.monotonic_time
        self.wanted = False
        self._armed_at = math.inf
        self._pressed = False
        self._config = None
        self.text = ""
        self.set_texts("暂停中", "点一下继续")
        pet.moved.connect(self.follow)

    def set_texts(self, text: str, tooltip: str, fallback=()) -> None:
        config = (text, tooltip, tuple(fallback))
        if config == self._config:
            return
        self._config = config
        self.text = text
        self.setToolTip(tooltip)
        self.setFont(label_font(fallback))
        self.resize_to(self.pet.sprite_height)
        self.update()

    def resize_to(self, _sprite_height: int) -> None:
        # 字号/内边距与气泡一致；宽度按三语文字实际测量。
        self.setFixedSize(*badge_size(self.text, self.font()))
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), CORNER_RADIUS, CORNER_RADIUS)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))
        self.follow()

    def set_wanted(self, on: bool) -> None:
        self.wanted = on
        if not on:
            self._pressed = False
        self.refresh()

    def refresh(self) -> None:
        if self.wanted and self.pet.isVisible():
            self.follow()
            if not self.isVisible():
                self.show()
                self.raise_()
        elif self.isVisible():
            self.hide()

    def showEvent(self, event) -> None:
        self._armed_at = self._clock() + ARM_DELAY
        self._pressed = False
        super().showEvent(event)

    def follow(self) -> None:
        if not self.wanted:
            return
        avail = self.pet._screen_avail(self.pet.geometry().center())
        x, y = badge_geometry(self.pet.body_rect(), (self.width(), self.height()),
                             (avail.x(), avail.y(), avail.width(), avail.height()), self.pet._jump_offset)
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    def mousePressEvent(self, event) -> None:
        self._pressed = (event.button() == Qt.LeftButton and self._clock() >= self._armed_at
                         and self.rect().contains(event.position().toPoint()))
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            event.ignore()
            return
        accepted = (self._pressed and self.wanted and self.isVisible()
                    and self._clock() >= self._armed_at and self.rect().contains(event.position().toPoint()))
        self._pressed = False
        if accepted:
            self.activated.emit()
        event.accept()

    def keyPressEvent(self, event) -> None:
        event.ignore()

    def keyReleaseEvent(self, event) -> None:
        event.ignore()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        paint_badge(p, (self.width(), self.height()), self.text, self.font())
        p.end()
