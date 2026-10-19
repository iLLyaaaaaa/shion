"""透明置顶的桌宠窗口：显示精灵、拖动、松手重力下落。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QPoint, QRect, QTimer, Qt, Signal
from PySide6.QtGui import QBitmap, QGuiApplication, QPainter, QPixmap, QRegion
from PySide6.QtWidgets import QMenu, QWidget

SPRITE_DIR = Path(__file__).resolve().parent.parent / "assets" / "sprites"
STATES = [
    "idle", "blink", "happy", "proud", "stop", "dizzy",
    "working", "done", "sleep", "drag", "neglect1", "neglect2",
]

DEFAULT_HEIGHT = 240
DRAG_THRESHOLD = 6  # px，超过才算拖动
GRAVITY = 2400.0  # px/s²
FRAME_MS = 16


def landing_geometry(avail: QRect, size_w: int, size_h: int, x: int) -> tuple[int, int]:
    """把窗口 x 限制在可用区域内，返回 (x, 脚底贴底边时的 y)。"""
    x = max(avail.left(), min(x, avail.right() + 1 - size_w))
    floor_y = avail.bottom() + 1 - size_h
    return x, floor_y


class PetWindow(QWidget):
    quit_requested = Signal()

    def __init__(self, height: int = DEFAULT_HEIGHT):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("Shion")

        self._height = height
        self._sprite_name = "idle"
        self._pix = QPixmap()
        self._base_sprite = "idle"  # 拖动结束后回到的精灵

        # 拖动 / 下落
        self._press_global: QPoint | None = None
        self._grab_offset = QPoint()
        self._dragging = False
        self._falling = False
        self._vy = 0.0
        self._fy = 0.0  # 下落时的浮点 y
        self._fall_floor = 0
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._fall_tick)

        self.set_sprite("idle")

    # ---- 精灵 ----
    def set_sprite(self, name: str) -> None:
        if name not in STATES:
            raise ValueError(f"未知精灵：{name}")
        screen = QGuiApplication.primaryScreen()
        dpr = screen.devicePixelRatio() if screen else 1.0
        src = QPixmap(str(SPRITE_DIR / f"{name}.png"))
        if src.isNull():
            raise FileNotFoundError(SPRITE_DIR / f"{name}.png")
        pix = src.scaledToHeight(round(self._height * dpr), Qt.SmoothTransformation)
        pix.setDevicePixelRatio(dpr)
        self._pix = pix
        self._sprite_name = name
        w, h = round(pix.width() / dpr), round(pix.height() / dpr)
        self.setFixedSize(w, h)
        # 只有不透明像素响应鼠标，透明区域点穿到下面的窗口
        self.setMask(QRegion(QBitmap.fromPixmap(pix.mask().scaled(w, h))))
        self.update()

    @property
    def sprite_name(self) -> str:
        return self._sprite_name

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawPixmap(0, 0, self._pix)

    # ---- 位置 ----
    def _screen_avail(self, at: QPoint | None = None) -> QRect:
        screen = (QGuiApplication.screenAt(at) if at else None) or QGuiApplication.primaryScreen()
        return screen.availableGeometry()

    def place_default(self) -> None:
        """主屏可用区域右下角，脚底贴底边。"""
        avail = QGuiApplication.primaryScreen().availableGeometry()
        x, y = landing_geometry(avail, self.width(), self.height(), avail.right() - self.width() - 24)
        self.move(x, y)

    # ---- 鼠标：拖动 ----
    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self._stop_fall()
            self._press_global = e.globalPosition().toPoint()
            self._grab_offset = self._press_global - self.pos()
            self._dragging = False
            e.accept()

    def mouseMoveEvent(self, e) -> None:
        if self._press_global is None or not (e.buttons() & Qt.LeftButton):
            return
        gp = e.globalPosition().toPoint()
        if not self._dragging:
            if (gp - self._press_global).manhattanLength() <= DRAG_THRESHOLD:
                return
            self._dragging = True
            self.set_sprite("drag")
            self.setCursor(Qt.ClosedHandCursor)
        self.move(gp - self._grab_offset)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() != Qt.LeftButton or self._press_global is None:
            return
        was_dragging = self._dragging
        self._press_global = None
        self._dragging = False
        self.unsetCursor()
        if was_dragging:
            self.start_fall()

    def contextMenuEvent(self, e) -> None:
        # 第 4 步会补全菜单；目前只有退出，方便结束程序
        menu = QMenu(self)
        menu.addAction("退出").triggered.connect(self.quit_requested.emit)
        menu.exec(e.globalPos())

    # ---- 下落 ----
    def start_fall(self) -> None:
        avail = self._screen_avail(self.geometry().center())
        x, floor_y = landing_geometry(avail, self.width(), self.height(), self.x())
        self._fall_floor = floor_y
        self.move(x, min(self.y(), floor_y))  # 在底边以下就先拉回底边
        self._fy = float(self.y())
        self._vy = 0.0
        self._falling = True
        self._clock.start()
        self._timer.start()
        self._fall_tick()

    def _stop_fall(self) -> None:
        self._falling = False
        self._timer.stop()

    def _fall_tick(self) -> None:
        dt = min(self._clock.restart() / 1000.0, 0.05)
        self._vy += GRAVITY * dt
        self._fy += self._vy * dt
        if self._fy >= self._fall_floor:
            self._fy = float(self._fall_floor)
            self.move(self.x(), self._fall_floor)
            self._stop_fall()
            self.set_sprite(self._base_sprite)  # 落地压扁等动画是第 2 步
            return
        self.move(self.x(), round(self._fy))

    @property
    def is_falling(self) -> bool:
        return self._falling

    @property
    def is_dragging(self) -> bool:
        return self._dragging
