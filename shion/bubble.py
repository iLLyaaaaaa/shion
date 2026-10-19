"""终端风格对话气泡：打字机效果、停留后淡出、跟随桌宠头顶。

BubbleTimeline 和 place_bubble 是纯 Python（可测试）；BubbleWindow 负责画出来。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from PySide6.QtCore import QPoint, QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QFontMetricsF, QGuiApplication, QImage, QPainter,
    QTextLayout, QTextOption,
)
from PySide6.QtWidgets import QWidget

CHAR_INTERVAL = 0.030  # 每 30ms 出一个字
HOLD = 4.0  # 全部显示后停留
FADE = 0.3  # 淡出时长

BG = QColor("#0A0A0A")
BORDER = QColor("#F58236")
FG = QColor("#FCF2E6")
FONT_CANDIDATES = ("Cascadia Mono", "Consolas")
FONT_PX = 13
PREFIX = "> "
PAD_X, PAD_Y = 9, 6
MAX_TEXT_W = 240  # 正文最大宽度（不含前缀和内边距）
GAP = 6  # 气泡和精灵之间的空隙


# ---------------------------------------------------------------- 纯逻辑

class BubbleTimeline:
    """一句台词的时间线。时间单位是秒，由外部传入。"""

    def __init__(self) -> None:
        self.text = ""
        self._t0: Optional[float] = None

    def start(self, now: float, text: str) -> None:
        """开始新台词；直接替换旧的。"""
        self.text = text
        self._t0 = now

    @property
    def active(self) -> bool:
        return self._t0 is not None

    def _type_end(self) -> float:
        return len(self.text) * CHAR_INTERVAL

    def visible_chars(self, now: float) -> int:
        if self._t0 is None:
            return 0
        n = int((now - self._t0) / CHAR_INTERVAL + 1e-9)  # 加 1e-9 防浮点误差
        return max(0, min(len(self.text), n))

    def opacity(self, now: float) -> float:
        if self._t0 is None:
            return 0.0
        t = now - self._t0 - self._type_end() - HOLD
        if t <= 0:
            return 1.0
        return max(0.0, 1.0 - t / FADE)

    def finished(self, now: float) -> bool:
        return self._t0 is None or self.opacity(now) <= 0.0

    def clear(self) -> None:
        self.text = ""
        self._t0 = None


def place_bubble(
    body: tuple[int, int, int, int],
    size: tuple[int, int],
    avail: tuple[int, int, int, int],
    gap: int = GAP,
) -> tuple[int, int]:
    """返回气泡左上角（屏幕坐标）。

    body：精灵本体的矩形 (x, y, w, h)。默认放在头顶正上方并居中；
    上方放不下就翻到脚下；两边都放不下就夹在屏幕内。水平方向始终夹进可用区域。
    """
    bx, by, bw, bh = body
    w, h = size
    ax, ay, aw, ah = avail
    x = bx + bw // 2 - w // 2
    x = max(ax, min(x, ax + aw - w))
    y = by - gap - h
    if y < ay:
        below = by + bh + gap
        y = below if below + h <= ay + ah else y
    y = max(ay, min(y, ay + ah - h))
    return x, y


def pick_font_family(available: Iterable[str], fixed_fallback: str) -> str:
    have = set(available)
    for name in FONT_CANDIDATES:
        if name in have:
            return name
    return fixed_fallback


# ---------------------------------------------------------------- 窗口

@dataclass
class _Line:
    start: int
    length: int
    y: float
    ascent: float


class BubbleWindow(QWidget):
    def __init__(self, clock: Callable[[], float] = time.perf_counter, autostart: bool = True):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
            | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self._clock = clock
        self._autostart = autostart
        self._timeline = BubbleTimeline()
        self._body: Optional[tuple[int, int, int, int]] = None

        family = pick_font_family(
            QFontDatabase.families(), QFontDatabase.systemFont(QFontDatabase.FixedFont).family()
        )
        self._font = QFont(family)
        self._font.setPixelSize(FONT_PX)
        self._font.setStyleHint(QFont.Monospace)
        self._lines: list[_Line] = []
        self._text_w = 0.0
        self._prefix_w = QFontMetricsF(self._font).horizontalAdvance(PREFIX)

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    # ---- 对外接口 ----
    def set_font_fallback(self, families: Iterable[str]) -> None:
        """首选字体不变，其后追加备选字体（日文、中文字符用得上）；改完重新排版并量前缀宽度。"""
        have = set(QFontDatabase.families())
        extra = [f for f in families if f in have and f != self._font.family()]
        self._font.setFamilies([self._font.family(), *extra])
        self._prefix_w = QFontMetricsF(self._font).horizontalAdvance(PREFIX)
        self._lines = []

    @property
    def font_family(self) -> str:
        return self._font.family()

    @property
    def timeline(self) -> BubbleTimeline:
        return self._timeline

    @property
    def line_count(self) -> int:
        return len(self._lines)

    def say(self, text: str) -> None:
        """开始说一句；正在说的会被直接替换。"""
        self._timeline.start(self._clock(), text)
        self._layout(text)
        self._place()
        if not self.isVisible():
            self.show()
        if self._autostart and not self._timer.isActive():
            self._timer.start()
        self.update()

    def follow(self, body: tuple[int, int, int, int]) -> None:
        """桌宠移动时调用：body 是精灵本体的屏幕矩形 (x, y, w, h)。"""
        self._body = body
        if self.isVisible():
            self._place()

    def dismiss(self) -> None:
        self._timeline.clear()
        self._timer.stop()
        self.hide()

    # ---- 排版 ----
    def _layout(self, text: str) -> None:
        """对完整文本一次性折行，窗口大小按完整文本定，打字过程中不会抖动。"""
        layout = QTextLayout(text, self._font)
        opt = QTextOption()
        opt.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(opt)
        layout.beginLayout()
        y = 0.0
        lines: list[_Line] = []
        widest = 0.0
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(MAX_TEXT_W)
            line.setPosition(QPointF(0, y))
            lines.append(_Line(line.textStart(), line.textLength(), y, line.ascent()))
            widest = max(widest, line.naturalTextWidth())
            y += line.height()
        layout.endLayout()
        if not lines:
            lines = [_Line(0, 0, 0.0, QFontMetricsF(self._font).ascent())]
            y = QFontMetricsF(self._font).height()
        self._lines = lines
        self._text_w = widest
        w = int(self._prefix_w + widest + 2 * PAD_X) + 2
        h = int(y + 2 * PAD_Y) + 2
        self.setFixedSize(w, h)

    def _place(self) -> None:
        if self._body is None:
            return
        bx, by, bw, bh = self._body
        screen = QGuiApplication.screenAt(QPoint(bx + bw // 2, by + bh // 2)) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        x, y = place_bubble(
            self._body, (self.width(), self.height()), (g.x(), g.y(), g.width(), g.height())
        )
        self.move(x, y)

    # ---- 绘制 ----
    def _tick(self) -> None:
        if self._timeline.finished(self._clock()):
            self.dismiss()
            return
        self.update()

    def _paint(self, p: QPainter, now: float) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(self._timeline.opacity(now))
        w, h = self.width(), self.height()
        p.setBrush(BG)
        p.setPen(BORDER)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 4, 4)

        p.setFont(self._font)
        p.setPen(FG)
        text = self._timeline.text
        shown = self._timeline.visible_chars(now)
        x0 = 1 + PAD_X
        y0 = 1 + PAD_Y
        for i, ln in enumerate(self._lines):
            n = min(ln.length, shown - ln.start)
            if n <= 0 and i > 0:
                break  # 这一行还没轮到
            base = y0 + ln.y + ln.ascent
            p.drawText(QPointF(x0, base), PREFIX.rstrip())  # 每行开头都有 "> "
            if n > 0:
                p.drawText(QPointF(x0 + self._prefix_w, base), text[ln.start : ln.start + n])

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        self._paint(p, self._clock())

    def render_image(self, now: Optional[float] = None) -> QImage:
        """离屏画一帧（截图和测试用）。"""
        img = QImage(self.size(), QImage.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        self._paint(p, self._clock() if now is None else now)
        p.end()
        return img
