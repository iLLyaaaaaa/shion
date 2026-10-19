"""飘心粒子。Particles 是纯 Python（可测试），HeartOverlay 负责画出来。"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Callable, Optional

from PySide6.QtCore import QPoint, QPointF, QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

from shion.animator import ease_out

LIFETIME = 1.0  # 秒
RISE = 70.0  # px
ORANGE = QColor("#F58236")


@dataclass
class Particle:
    born: float
    x0: float  # 相对中心的水平起点
    drift: float  # 水平漂移总量
    size: float


class Particles:
    def __init__(self, rng: Optional[random.Random] = None):
        self._rng = rng or random.Random()
        self._ps: list[Particle] = []

    def spawn(self, now: float, n: int = 1) -> None:
        for _ in range(n):
            self._ps.append(
                Particle(
                    born=now,
                    x0=self._rng.uniform(-25, 25),
                    drift=self._rng.uniform(-15, 15),
                    size=self._rng.uniform(0.8, 1.2),
                )
            )

    def update(self, now: float) -> None:
        self._ps = [p for p in self._ps if now - p.born < LIFETIME]

    @property
    def active(self) -> bool:
        return bool(self._ps)

    def items(self, now: float) -> list[tuple[float, float, float, float]]:
        """每个粒子 (x, y, scale, alpha)；y 向上为负，0 是出生点。"""
        out = []
        for p in self._ps:
            t = (now - p.born) / LIFETIME
            if not 0 <= t < 1:
                continue
            eased = ease_out(t)
            out.append((p.x0 + p.drift * eased, -RISE * eased, p.size, 1.0 - t * t))
        return out


def heart_path(size: float) -> QPainterPath:
    """以 (0,0) 为中心、宽约 size 的爱心。"""
    s = size / 2
    path = QPainterPath()
    path.moveTo(0, s * 0.9)
    path.cubicTo(-s * 1.5, -s * 0.2, -s * 0.6, -s * 1.2, 0, -s * 0.4)
    path.cubicTo(s * 0.6, -s * 1.2, s * 1.5, -s * 0.2, 0, s * 0.9)
    return path


class HeartOverlay(QWidget):
    """完全不接收鼠标的透明小窗口，跟着桌宠头顶，只在有粒子时显示。"""

    SIZE = 160

    def __init__(self, clock: Callable[[], float] = time.perf_counter, autostart: bool = True):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
            | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(self.SIZE, self.SIZE)
        self._clock = clock
        self._particles = Particles()
        self._anchor = QPoint(0, 0)  # 出生点（全局坐标）
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self.tick)
        self._autostart = autostart

    @property
    def particles(self) -> Particles:
        return self._particles

    def burst(self, anchor: QPoint, n: int = 1) -> None:
        self._anchor = anchor
        self.move(anchor.x() - self.SIZE // 2, anchor.y() - self.SIZE + 20)
        self._particles.spawn(self._clock(), n)
        if not self.isVisible():
            self.show()
        if self._autostart and not self._timer.isActive():
            self._timer.start()
        self.update()

    def follow(self, anchor: QPoint) -> None:
        self._anchor = anchor
        self.move(anchor.x() - self.SIZE // 2, anchor.y() - self.SIZE + 20)

    def tick(self) -> None:
        now = self._clock()
        self._particles.update(now)
        if not self._particles.active:
            self._timer.stop()
            self.hide()
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        now = self._clock()
        for x, y, scale, alpha in self._particles.items(now):
            p.save()
            p.translate(QPointF(self.SIZE / 2 + x, self.SIZE - 20 + y))
            c = QColor(ORANGE)
            c.setAlphaF(max(0.0, min(1.0, alpha)))
            p.setBrush(c)
            p.setPen(Qt.NoPen)
            p.drawPath(heart_path(22 * scale))
            p.restore()
