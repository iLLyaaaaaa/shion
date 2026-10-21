"""调试用实际绘制计数；文字窗口独立刷新，不驱动桌宠重绘。"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel
from shion.windowing import set_topmost

FPS_INTERVAL = 0.5


class PaintCounter:
    def __init__(self, now: float):
        self.reset(now)

    def reset(self, now: float) -> None:
        self.start = now
        self.paints = 0
        self.fps: float | None = None

    def record(self) -> None:
        self.paints += 1

    def sample(self, now: float) -> float | None:
        elapsed = now - self.start
        if elapsed + 1e-9 >= FPS_INTERVAL:
            self.fps = self.paints / elapsed
            self.paints = 0
            self.start = now
        return self.fps


class FpsOverlay(QLabel):
    def __init__(self, pet, clock):
        super().__init__(pet, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        set_topmost(self, bool(pet.windowFlags() & Qt.WindowStaysOnTopHint))
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(88, 24)
        self.setStyleSheet("color: #FCF2E6; background: #0A0A0A; border: 1px solid #F58236;"
                           "font-family: Consolas; font-size: 12px; padding-left: 5px;")
        self.setText("FPS: --")
        self.pet = pet
        self.clock = clock
        self.counter = PaintCounter(clock())
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.setInterval(round(FPS_INTERVAL * 1000))
        self.timer.timeout.connect(self.tick)
        pet.moved.connect(self.follow)

    def resume(self) -> None:
        self.counter.reset(self.clock())
        self.setText("FPS: --")
        self.follow()
        self.show()
        self.timer.start()

    def pause(self) -> None:
        self.timer.stop()
        self.hide()

    def follow(self) -> None:
        x, y, w, h = self.pet.body_rect()
        avail = self.pet._screen_avail(self.pet.geometry().center())
        want_x = x + w + 6
        if want_x + self.width() > avail.right() + 1:
            want_x = x - self.width() - 6
        want_y = y + round(h * 0.35 - self.pet._jump_offset)
        self.move(max(avail.left(), min(want_x, avail.right() + 1 - self.width())),
                  max(avail.top(), min(want_y, avail.bottom() + 1 - self.height())))

    def tick(self) -> None:
        value = self.counter.sample(self.clock())
        self.setText("FPS: --" if value is None else f"FPS: {value:.1f}")
        self.follow()
