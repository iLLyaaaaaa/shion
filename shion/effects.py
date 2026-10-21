"""飘心粒子。Particles 是纯 Python（可测试），HeartOverlay 负责画出来。"""
from __future__ import annotations

import random
import time
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QPoint, QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath
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

# Z 的距离/尺寸均以本体高 200 逻辑像素为基准，所有四档大小同比缩放。
Z_BASE_HEIGHT = 200.0
Z_INTERVAL = 0.9
Z_MAX_PARTICLES = 3
Z_LIFETIME = 2.4
Z_DRIFT = 40.0  # 向右上总路程
Z_SCALE = (0.5, 1.0)
Z_SWING_DEGREES = 8.0
Z_SWING_PERIOD = 1.2
Z_FADE_START = 2 / 3
Z_WAKE_FADE = 0.15
Z_SIZE = 24.0
Z_OVERLAY_SIZE = 128.0
Z_ORIGIN = (32.0, 96.0)
Z_ANCHORS = {"sleep": (0.88, 0.23), "bed": (0.70, 0.18)}
Z_CANVAS_ASPECT = {"sleep": 448 / 512, "bed": 640 / 512}


class SleepZParticles:
    """睡眠粒子独立时间线；掉帧不补发，唤醒时从当前透明度立即淡出。"""

    def __init__(self):
        self.born: list[float] = []
        self.sleeping = False
        self.last_spawn = -math.inf
        self.wake_at = math.inf

    def clear(self) -> None:
        self.__init__()

    def update(self, now: float, sleeping: bool) -> None:
        if sleeping and not self.sleeping:
            self.born.clear()  # 不让上次起床尚未消失的 Z 重新变亮
            self.last_spawn = -math.inf
            self.wake_at = math.inf
        elif not sleeping and self.sleeping:
            self.wake_at = now
        self.sleeping = sleeping
        self.born = [born for born in self.born if now - born < Z_LIFETIME]
        if now - self.wake_at >= Z_WAKE_FADE - 1e-9:
            self.born.clear()
        if (sleeping and now - self.last_spawn >= Z_INTERVAL - 1e-9
                and len(self.born) < Z_MAX_PARTICLES):
            self.born.append(now)
            self.last_spawn = now

    def items(self, now: float) -> list[tuple[float, float, float, float, float]]:
        result = []
        wake_alpha = max(0.0, min(1.0, 1 - (now - self.wake_at) / Z_WAKE_FADE))
        for born in self.born:
            age = now - born
            p = age / Z_LIFETIME
            if not 0 <= p < 1:
                continue
            # 匀速让相邻发射保持间距，避免末端减速时三枚 Z 堆在一起。
            distance = Z_DRIFT * p / math.sqrt(2)
            scale = Z_SCALE[0] + (Z_SCALE[1] - Z_SCALE[0]) * p
            angle = Z_SWING_DEGREES * math.sin(math.tau * age / Z_SWING_PERIOD)
            alpha = min(1.0, (1 - p) / (1 - Z_FADE_START)) * wake_alpha
            if alpha > 0:
                result.append((distance, -distance, scale, angle, alpha))
        return result


def sleep_z_anchor(pet, state: str) -> QPoint:
    x, y = Z_ANCHORS[state]
    height = pet.sprite_height
    # 按各自素材画布宽计算，淡化收窄时仍以脚底中心为准。
    return pet.mapToGlobal(QPoint(round(pet.width() / 2 + (x - .5) * height * Z_CANVAS_ASPECT[state]),
                                 round(pet.body_rect()[1] - pet.y() + y * height)))


class SleepZOverlay(QWidget):
    """由桌宠帧时钟驱动的 Z 窗口；完全点穿，不加入身体 mask。"""

    def __init__(self, pet, sprite_path: Path):
        super().__init__(pet)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowTransparentForInput
                            | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.pet = pet
        self.particles = SleepZParticles()
        self.image = QImage(str(sprite_path))
        self.state = "sleep"
        self.scale = 1.0
        self.now = 0.0

    def follow(self) -> None:
        self.scale = self.pet.sprite_height / Z_BASE_HEIGHT
        size = math.ceil(Z_OVERLAY_SIZE * self.scale)
        self.setFixedSize(size, size)
        anchor = sleep_z_anchor(self.pet, self.state)
        self.move(anchor.x() - round(Z_ORIGIN[0] * self.scale),
                  anchor.y() - round(Z_ORIGIN[1] * self.scale))

    def advance(self, now: float, state: str | None) -> None:
        if state is not None:
            if state != self.state:
                self.particles.clear()
            self.state = state
        self.now = now
        self.particles.update(now, state is not None)
        self.follow()
        self.setVisible(self.pet.isVisible() and bool(self.particles.items(now)) and not self.image.isNull())
        self.update()

    def draw(self, painter: QPainter, origin: QPointF) -> None:
        if self.image.isNull():
            return
        painter.save()
        painter.setRenderHints(QPainter.SmoothPixmapTransform | QPainter.Antialiasing)
        painter.translate(origin)
        painter.scale(self.scale, self.scale)
        for x, y, scale, angle, alpha in self.particles.items(self.now):
            painter.save()
            painter.translate(x, y)
            painter.rotate(angle)
            painter.setOpacity(alpha)
            width = Z_SIZE * scale
            height = width * self.image.height() / self.image.width()
            painter.drawImage(QRectF(-width / 2, -height / 2, width, height), self.image)
            painter.restore()
        painter.restore()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        self.draw(painter, QPointF(Z_ORIGIN[0] * self.scale, Z_ORIGIN[1] * self.scale))
        painter.end()

    def stop(self) -> None:
        self.particles.clear()
        self.hide()


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
