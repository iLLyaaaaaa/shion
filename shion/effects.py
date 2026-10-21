"""飘心粒子。Particles 是纯 Python（可测试），HeartOverlay 负责画出来。"""
from __future__ import annotations

import random
import time
import math
from dataclasses import dataclass
from typing import Callable, Optional

from PySide6.QtCore import QPoint, QPointF, QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

from shion.animator import ease_out

LIFETIME = 1.0  # 秒
RISE = 55.0  # px
SPAWN_INTERVAL = 0.2
MAX_PARTICLES = 6
HEART_SIZE = 20.0
PAT_START_PARTICLES = 2
HEART_SPREAD = 25.0
HEART_DRIFT = 15.0
HEART_SCALE = (0.8, 1.2)
ORANGE = QColor("#F58236")
MOUTH_FRACTION = 0.45


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
        self._last_spawn = -float("inf")

    def spawn(self, now: float, n: int = 1, *, start_session: bool = False) -> None:
        """新摸头过程立即冒两颗；后续按间隔冒一颗，始终守总数上限且不补播。"""
        self.update(now)
        if (n <= 0 or len(self._ps) >= MAX_PARTICLES
                or not start_session and now - self._last_spawn + 1e-9 < SPAWN_INTERVAL):
            return
        self._last_spawn = now
        count = min(PAT_START_PARTICLES if start_session else 1, MAX_PARTICLES - len(self._ps))
        for _ in range(count):
            self._ps.append(
                Particle(
                    born=now,
                    x0=self._rng.uniform(-HEART_SPREAD, HEART_SPREAD),
                    drift=self._rng.uniform(-HEART_DRIFT, HEART_DRIFT),
                    size=self._rng.uniform(*HEART_SCALE),
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


class Celebration:
    """升级的一圈爱心，独立于摸头粒子的频率和数量限制。"""

    COUNT = 12

    def __init__(self):
        self.born = -float("inf")

    def start(self, now: float) -> None:
        self.born = now

    def items(self, now: float) -> list[tuple[float, float, float, float]]:
        t = (now - self.born) / LIFETIME
        if not 0 <= t < 1:
            return []
        radius = 27 + 18 * ease_out(t)
        return [(radius * math.cos(i * math.tau / self.COUNT),
                 -60 + radius * math.sin(i * math.tau / self.COUNT), 0.7, 1 - t * t)
                for i in range(self.COUNT)]


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
        self.celebration = Celebration()
        self._anchor = QPoint(0, 0)  # 出生点（全局坐标）
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self.tick)
        self._autostart = autostart

    @property
    def particles(self) -> Particles:
        return self._particles

    def burst(self, anchor: QPoint, n: int = 1, *, start_session: bool = False) -> None:
        self._anchor = anchor
        self.move(anchor.x() - self.SIZE // 2, anchor.y() - self.SIZE + 20)
        self._particles.spawn(self._clock(), n, start_session=start_session)
        if not self.isVisible():
            self.show()
        if self._autostart and not self._timer.isActive():
            self._timer.start()
        self.update()

    def follow(self, anchor: QPoint) -> None:
        self._anchor = anchor
        self.move(anchor.x() - self.SIZE // 2, anchor.y() - self.SIZE + 20)

    def celebrate(self, anchor: QPoint) -> None:
        self.follow(anchor)
        self.celebration.start(self._clock())
        self.show()
        if self._autostart and not self._timer.isActive():
            self._timer.start()
        self.update()

    def tick(self) -> None:
        now = self._clock()
        self._particles.update(now)
        if not self._particles.active and not self.celebration.items(now):
            self._timer.stop()
            self.hide()
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        now = self._clock()
        for x, y, scale, alpha in self._particles.items(now) + self.celebration.items(now):
            p.save()
            p.translate(QPointF(self.SIZE / 2 + x, self.SIZE - 20 + y))
            c = QColor(ORANGE)
            c.setAlphaF(max(0.0, min(1.0, alpha)))
            p.setBrush(c)
            p.setPen(Qt.NoPen)
            p.drawPath(heart_path(HEART_SIZE * scale))
            p.restore()


class Crumbs:
    """有上限的碎屑，掉帧时不补发；时间全部由调用方传入。"""

    LIFETIME = 0.65
    INTERVAL = 0.16
    MAX = 18

    def __init__(self, rng=None):
        self._rng = rng or random.Random()
        self._ps = []
        self._until = 0.0
        self._last = -float("inf")

    def start(self, now: float, duration: float = 2.0) -> None:
        self._ps.clear()
        self._until = now + duration
        self._last = -float("inf")
        self.update(now)

    def update(self, now: float) -> None:
        self._ps = [p for p in self._ps if now - p[0] < self.LIFETIME]
        if now < self._until and now - self._last >= self.INTERVAL:
            self._last = now
            for _ in range(min(3, self.MAX - len(self._ps))):
                self._ps.append((now, self._rng.uniform(-24, 24), self._rng.uniform(3, 5)))

    @property
    def active(self) -> bool:
        return bool(self._ps)

    def items(self, now: float):
        result = []
        for born, drift, size in self._ps:
            t = (now - born) / self.LIFETIME
            if 0 <= t < 1:
                result.append((drift * ease_out(t), 50 * t * t, size, 1 - t))
        return result


class CrumbOverlay(HeartOverlay):
    """嘴边碎屑；沿用透明、不抢焦点和点穿的窗口设置。"""

    def __init__(self, clock=time.perf_counter, autostart=True):
        super().__init__(clock=clock, autostart=autostart)
        self._particles = Crumbs()
        self._scale = 1.0

    def start(self, anchor: QPoint, height: int, duration: float = 2.0) -> None:
        self._scale = height / 200
        self._particles.start(self._clock(), duration)
        self.follow(anchor)
        self.show()
        if self._autostart:
            self._timer.start()
        self.update()

    def follow(self, anchor: QPoint) -> None:
        self._anchor = anchor
        self.move(anchor.x() - self.SIZE // 2, anchor.y() - 40)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        for x, y, size, alpha in self._particles.items(self._clock()):
            color = QColor("#E5B77B")
            color.setAlphaF(alpha)
            p.setBrush(color)
            p.drawEllipse(QPointF(self.SIZE / 2 + x * self._scale, 40 + y * self._scale),
                          size * self._scale / 2, size * self._scale / 2)
