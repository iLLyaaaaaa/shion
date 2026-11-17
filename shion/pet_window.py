"""透明置顶的桌宠窗口骨架：窗口属性、信号、拖动、原地停放、重力下落和夹边。

怎么画（贴图、遮罩、刷新、睡觉 Z）由子类 V3PetWindow 实现；这里的 _load_sprites / _draw_sprite /
_mask_for / _refresh / _sync_sleep_z 只是接口，PetWindow 本身不能单独实例化。

窗口画布比人物大一圈（留边），这样倾斜、晃动时不会被裁掉。
脚底中心固定在画布底边的中点，所有变换都以它为锚点。
"""
from __future__ import annotations

import math
import os
import random
import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QPoint, QRect, QTimer, Qt, Signal
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QRegion
from PySide6.QtWidgets import QWidget

from shion.animator import Animator, Frame
from shion.behavior import (
    JUMP_HEIGHT, LEGACY_JUMP_DURATION, LEGACY_JUMP_HEIGHT,
    SHAKE_WINDOW, DragPlayback, ShakeTracker,
    ReleaseVelocity, RELEASE_FAST_SPEED,
)

SPRITE_DIR = Path(__file__).resolve().parent.parent / "assets" / "sprites"
STATES = [
    "idle", "blink", "happy", "proud", "stop", "dizzy",
    "working", "done", "sleep", "drag", "neglect1", "neglect2",
    "yawn", "slump", "collapse", "cheer",
]
PROP_STATES = ("bed", "desk")
SEQUENCE_GROUPS = ("jump", "drag", "tickle", "cheek", "bed", "desk")  # 状态名里的分组前缀（expression_for 用）

DEFAULT_HEIGHT = 200
MARGIN_X = 64  # 画布左右留边（倾斜 12° 时头部偏移约 50px）
MARGIN_TOP = round(JUMP_HEIGHT) + 8  # 给原地跳留出空间
MARGIN_BOTTOM = 6  # 倾斜时一只脚会往下沉，留出空间不被裁掉
MASK_GROW = 4  # 遮罩向外扩的像素，吸收角度/缩放量化的误差
PAT_DISTANCE = 40  # px，摸头累计移动多少算一次
DRAG_THRESHOLD = 6  # px，超过才算拖动
GRAVITY = 2400.0  # px/s²
FRAME_MS = 16


def landing_geometry(
    avail: QRect, size_w: int, size_h: int, x: int,
    margin_x: int = 0, margin_bottom: int = 0,
) -> tuple[int, int]:
    """返回 (x, 脚底贴底边时的 y)。

    x 被限制到让精灵本体（窗口左右各去掉 margin_x）不出可用区域；
    脚底锚点在窗口底边上方 margin_bottom 处。
    """
    lo = avail.left() - margin_x
    hi = avail.right() + 1 - size_w + margin_x
    x = max(lo, min(x, hi))
    floor_y = avail.bottom() + 1 - size_h + margin_bottom
    return x, floor_y


class PetWindow(QWidget):
    patted = Signal()  # 在头部左右移动，每累计 40px 一次
    clicked = Signal()  # 按下到松开几乎没动
    double_clicked = Signal()  # 在对应的 clicked 之后发出
    drag_started = Signal()
    drag_finished = Signal()  # 松手后落地时发出
    menu_requested = Signal(QPoint)  # 全局坐标
    moved = Signal()  # 窗口位置变了（气泡跟随用）
    pressed = Signal()  # 左键按下即中断自主运动
    gesture = Signal(str)  # cheek_pull / cheek_release / tickle / tickle_end / belly（静默）
    resume_requested = Signal()  # 检查点暂停标签，仅左键且防误点时间已过

    def __init__(
        self,
        height: int = DEFAULT_HEIGHT,
        clock: Callable[[], float] = time.perf_counter,
        autostart: bool = True,
        *, debug: bool | None = None,
        rng: random.Random | None = None,
        pixel_ratio: float | None = None,
    ):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle("Shion")
        self.setMouseTracking(True)

        self._clock = clock
        self._fps_overlay = None
        self._sleep_z = None
        self._pause_badge = None  # 暂停文字标签，第一次要显示时才建
        self._height = height
        self._pixel_ratio = pixel_ratio
        self._sw = 0  # 精灵逻辑宽高
        self._sh = 0
        self._load_sprites()
        self.setFixedSize(self._sw + 2 * MARGIN_X, self._sh + MARGIN_TOP + MARGIN_BOTTOM)

        self._animator = Animator(rng)
        self._frame = Frame("idle")

        # 拖动 / 下落
        self._press_global: QPoint | None = None
        self._grab_offset = QPoint()
        self._dragging = False
        self.release_to_taskbar = False
        self._release_velocity = ReleaseVelocity()
        self._last_drag_pos = QPoint()
        self._drag_playback: DragPlayback | None = None
        self._falling = False
        self._drag_active = False  # 已发 drag_started、尚未落地
        self._caught_fall = False  # 这次按下抓住了正在下落的桌宠
        self._pat_mode = False
        self._pat_accum = 0.0
        self._pat_last_x = 0
        self._moved = False  # 按下后移动超过阈值
        self._double = False
        self._vy = 0.0
        self._fy = 0.0  # 下落时的浮点 y
        self._fall_floor = 0
        self._fall_start = 0.0
        self._fall_y0 = 0.0
        self._last_tick = self._clock()
        self._shake = ShakeTracker()
        self._jump_start: float | None = None
        self._automatic_jump = False
        self._jump_offset = 0.0

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._on_timer)

        self.set_state("idle")
        debug_enabled = debug if debug is not None else os.environ.get("SHION_DEBUG") == "1"
        if debug_enabled:
            from shion.debug import FpsOverlay
            self._fps_overlay = FpsOverlay(self, clock)
        if autostart:
            self._timer.start()

    # ---- 精灵 ----
    def set_height(self, height: int) -> None:
        """改显示大小，脚底中心在屏幕上的位置不变。"""
        if height == self._height:
            return
        self.stop_motion()
        feet_x = self.x() + self.width() / 2
        feet_y = self.y() + self.height() - MARGIN_BOTTOM
        self._height = height
        self._load_sprites()
        self.setFixedSize(self._sw + 2 * MARGIN_X, self._sh + MARGIN_TOP + MARGIN_BOTTOM)
        self.move(round(feet_x - self.width() / 2), round(feet_y - self.height() + MARGIN_BOTTOM))
        if self._pause_badge is not None:
            self._pause_badge.resize_to(height)
        if self._falling:
            self.start_fall()  # 改大小后重算落点，仍按真实经过的秒数下落
        self._refresh(self._clock())

    @property
    def sprite_height(self) -> int:
        return self._height

    def snap_to_floor(self) -> None:
        """x 限制在屏幕内、脚底贴底边（改大小、恢复存档位置后用）。"""
        avail = self._screen_avail(self.geometry().center())
        x, y = landing_geometry(
            avail, self.width(), self.height(), self.x(), MARGIN_X, MARGIN_BOTTOM
        )
        self.move(x, y)

    def place_on(self, avail: tuple[int, int, int, int], x: int) -> None:
        """放到指定屏幕的可用区域里：x 夹进屏内，脚底贴那块屏的底边。"""
        r = QRect(*avail)
        nx, ny = landing_geometry(r, self.width(), self.height(), x, MARGIN_X, MARGIN_BOTTOM)
        self.move(nx, ny)

    def clamp_position(self, avail: QRect | None = None) -> None:
        """只把精灵本体夹回屏内，保留悬空的纵向位置。"""
        avail = avail if avail is not None else self._screen_avail(self.geometry().center())
        x, floor = landing_geometry(avail, self.width(), self.height(), self.x(), MARGIN_X, MARGIN_BOTTOM)
        self.move(x, max(avail.top() - MARGIN_TOP, min(self.y(), floor)))

    @property
    def is_floating(self) -> bool:
        avail = self._screen_avail(self.geometry().center())
        return self.y() + self.height() - MARGIN_BOTTOM < avail.bottom() + 1

    def head_anchor(self) -> QPoint:
        """头顶中心（全局坐标），给爱心和提示定位。"""
        return self.mapToGlobal(QPoint(self.width() // 2, MARGIN_TOP + int(self._sh * 0.08)))

    def body_rect(self) -> tuple[int, int, int, int]:
        """精灵本体的屏幕矩形 (x, y, w, h)，不含留边。"""
        return (self.x() + MARGIN_X, self.y() + MARGIN_TOP, self._sw, self._sh)

    def mouth_anchor(self) -> QPoint:
        """嘴部位置（全局坐标），喂零食的碎屑从这里掉。"""
        from shion.effects import MOUTH_FRACTION
        x, y, w, h = self.body_rect()
        return QPoint(x + w // 2, y + round(h * MOUTH_FRACTION))

    def start_chewing(self, seconds: float) -> None:
        """喂零食开始。基类什么也不做；V3 窗口点头咀嚼。"""

    def moveEvent(self, e) -> None:
        super().moveEvent(e)
        if self._sleep_z is not None:
            self._sleep_z.follow()
        self.moved.emit()

    # ---- 停下标记 ----
    def set_paused_badge(self, on: bool, *, text="暂停中", tooltip="点一下继续", fallback=()) -> None:
        """hook 真正在检查点停住后的文字标签；可见性由控制器决定。"""
        if self._pause_badge is None:
            if not on:
                return
            from shion.badge import PauseBadge
            self._pause_badge = PauseBadge(self)
            self._pause_badge.activated.connect(self.resume_requested.emit)
        self._pause_badge.set_texts(text, tooltip, fallback)
        self._pause_badge.set_wanted(on)

    @property
    def paused_badge_shown(self) -> bool:
        return self._pause_badge is not None and self._pause_badge.wanted

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._refresh(self._clock())
        if self._fps_overlay is not None:
            self._fps_overlay.resume()
        if self._pause_badge is not None:
            self._pause_badge.refresh()

    def hideEvent(self, e) -> None:
        if self._sleep_z is not None:
            self._sleep_z.stop()
        if self._fps_overlay is not None:
            self._fps_overlay.pause()
        if self._pause_badge is not None:
            self._pause_badge.hide()
        super().hideEvent(e)

    def closeEvent(self, e) -> None:
        self._timer.stop()
        if self._sleep_z is not None:
            self._sleep_z.stop()
        if self._fps_overlay is not None:
            self._fps_overlay.pause()
        if self._pause_badge is not None:
            self._pause_badge.hide()
        super().closeEvent(e)

    def _hit_zone(self, pos: QPoint) -> str:
        """窗口内的点是否落在人物本体范围（不含留边）：outside / body。手势分区由 V3 窗口按命中判断。"""
        sx = pos.x() - MARGIN_X
        sy = pos.y() - MARGIN_TOP
        if not (0 <= sx < self._sw and 0 <= sy < self._sh):
            return "outside"
        return "body"

    def _load_sprites(self) -> None:
        """载入画面素材并算出 _sw / _sh / normal_width；由 V3PetWindow 实现。"""
        raise NotImplementedError

    @property
    def sprite_size(self) -> tuple[int, int]:
        return self._sw, self._sh

    def set_state(self, name: str, *, animate: bool = True) -> None:
        if name not in STATES and name not in PROP_STATES:
            raise ValueError(f"未知精灵：{name}")
        now = self._clock()
        self._animator.set_state(name, now, immediate=not animate)
        self._refresh(now)

    @property
    def sprite_name(self) -> str:
        """当前底层状态（不含眨眼）。"""
        return self._animator.state

    @property
    def displayed_sprite(self) -> str:
        """此刻实际画出来的贴图（眨眼时是 blink）。"""
        return self._frame.sprite

    @property
    def frame(self) -> Frame:
        return self._frame

    # ---- 绘制 ----
    def _draw_sprite(self, p: QPainter, f: Frame) -> None:
        """把当前帧画到 p 上（脚底中心为锚点）；由 V3PetWindow 实现。"""
        raise NotImplementedError

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHints(QPainter.SmoothPixmapTransform | QPainter.Antialiasing)
        self._draw_sprite(p, self._frame)
        p.end()
        if self._fps_overlay is not None:
            self._fps_overlay.counter.record()

    def render_frame(self, scale: int = 1) -> QImage:
        """把当前帧画进一张透明 QImage（不受遮罩裁剪，截图和测试用）。"""
        img = QImage(self.size() * scale, QImage.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(scale)
        img.fill(0)
        p = QPainter(img)
        p.setRenderHints(QPainter.SmoothPixmapTransform | QPainter.Antialiasing)
        self._draw_sprite(p, self._frame)
        p.end()
        return img

    def _mask_for(self, f: Frame) -> QRegion:
        """响应鼠标的区域（当前画出的不透明像素向外扩 MASK_GROW px）；由 V3PetWindow 实现。"""
        raise NotImplementedError

    def _refresh(self, now: float) -> None:
        """按当前时间算出这一帧、更新窗口宽度、遮罩和重绘；由 V3PetWindow 实现。"""
        raise NotImplementedError

    def _sync_sleep_z(self, now: float, frame: Frame) -> None:
        """睡觉 Z 的显示与出发点；由 V3PetWindow 实现。"""
        raise NotImplementedError

    # ---- 位置 ----
    def _screen_avail(self, at: QPoint | None = None) -> QRect:
        screen = (QGuiApplication.screenAt(at) if at else None) or QGuiApplication.primaryScreen()
        return screen.availableGeometry()

    def place_default(self) -> None:
        """主屏可用区域右下角，脚底贴底边。"""
        avail = QGuiApplication.primaryScreen().availableGeometry()
        want_x = avail.right() + 1 - 24 - self._sw - MARGIN_X
        x, y = landing_geometry(
            avail, self.width(), self.height(), want_x, MARGIN_X, MARGIN_BOTTOM
        )
        self.move(x, y)

    # ---- 时钟 ----
    def monotonic_time(self) -> float:
        return self._clock()

    def _on_timer(self) -> None:
        self.advance_to(self._clock())

    def advance_to(self, now: float) -> None:
        """推进一帧：拖动速度、下落、动画。定时器和测试/截图都走这里。"""
        dt = max(0.0, now - self._last_tick)
        self._last_tick = now
        if self._jump_start is not None:
            elapsed = max(0.0, now - self._jump_start)
            p = max(0.0, min(1.0, elapsed / LEGACY_JUMP_DURATION))
            self._jump_offset = LEGACY_JUMP_HEIGHT * math.sin(math.pi * p)
            if elapsed + 1e-9 >= LEGACY_JUMP_DURATION:
                self._jump_start = None
                self._jump_offset = 0.0
        if self._dragging and dt > 0:
            delta = self.pos() - self._last_drag_pos
            vx = delta.x() / dt
            self._last_drag_pos = self.pos()
            self._animator.feed_velocity(vx, now)
            if self._drag_playback is not None:
                shakes = sum(now - mark <= SHAKE_WINDOW for mark in self._shake.marks)
                self._drag_playback.feed(now, math.hypot(delta.x(), delta.y()) / dt, shakes)
        if self._drag_playback is not None:
            self._drag_playback.advance(now)
        if self._falling:
            self._fall_step(now)
        self._refresh(now)

    # ---- 鼠标 ----
    def enterEvent(self, e) -> None:
        if not self._dragging:
            self._update_hover_cursor(e.position().toPoint())
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        if not self._dragging:
            self.unsetCursor()
        super().leaveEvent(e)

    def _update_hover_cursor(self, pos: QPoint) -> None:
        """悬停光标；手势区域的手形光标由 V3PetWindow 按命中判断，基类只还原默认光标。"""
        self.unsetCursor()

    def mousePressEvent(self, e) -> None:
        if e.button() != Qt.LeftButton:
            return
        self.stop_motion()
        self.pressed.emit()
        self._caught_fall = self._falling
        self._stop_fall()
        self._press_global = e.globalPosition().toPoint()
        self._release_velocity = ReleaseVelocity()
        self._release_velocity.feed(self._clock(), self._press_global.x(), self._press_global.y())
        self._grab_offset = self._press_global - self.pos()
        self._dragging = False
        self._moved = False
        self._pat_mode = False  # V3 窗口在“手势已被吃掉”时才在松手前置 True（见 V3PetWindow.mouseReleaseEvent）
        self._pat_accum = 0.0
        self._pat_last_x = self._press_global.x()
        e.accept()

    def mouseDoubleClickEvent(self, e) -> None:
        self._double = True
        self.mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:
        if self._press_global is None or not (e.buttons() & Qt.LeftButton):
            self._update_hover_cursor(e.position().toPoint())
            return
        gp = e.globalPosition().toPoint()
        self._release_velocity.feed(self._clock(), gp.x(), gp.y())
        if not self._moved:
            d = gp - self._press_global
            if math.hypot(d.x(), d.y()) <= DRAG_THRESHOLD:
                return  # 阈值内不算拖动（捏脸、摸头等手势由 V3 窗口自己处理）
            self._moved = True
        if not self._dragging:
            self._dragging = True
            now = self._clock()
            self._shake.reset(self._press_global.x())
            self._animator.set_drag(True, now)
            self._last_drag_pos = self.pos()
            self._last_tick = now
            self.setCursor(Qt.ClosedHandCursor)
            if not self._drag_active:
                self._drag_playback = DragPlayback(now)
                self._drag_active = True
                self.drag_started.emit()
        self._shake.feed(gp.x(), self._clock())
        self.move(gp - self._grab_offset)

    def _pat_step(self, gp: QPoint) -> None:
        self._pat_accum += abs(gp.x() - self._pat_last_x)
        self._pat_last_x = gp.x()
        while self._pat_accum >= PAT_DISTANCE:
            self._pat_accum -= PAT_DISTANCE
            self.patted.emit()

    def mouseReleaseEvent(self, e) -> None:
        if e.button() != Qt.LeftButton or self._press_global is None:
            return
        was_dragging = self._dragging
        was_pat = self._pat_mode and self._moved
        double = self._double
        caught = self._caught_fall
        now = self._clock()
        if was_dragging:
            self.advance_to(now)
            if self._drag_playback is not None:
                self._drag_playback.freeze(now)
        self._press_global = None
        self._dragging = False
        self._pat_mode = False
        self._double = False
        self._caught_fall = False
        self._animator.set_drag(False, self._clock())
        self._update_hover_cursor(e.position().toPoint())
        if was_dragging or caught:
            gp = e.globalPosition().toPoint()
            speed = self._release_velocity.speed(now, gp.x(), gp.y())
            if self.release_to_taskbar or speed >= RELEASE_FAST_SPEED:
                self.start_fall()
            else:
                self.clamp_position()
                self._drag_playback = None
                self._drag_active = False
                self.drag_finished.emit()
                self._animator.squash(now, "click")
                self._refresh(now)
        elif not was_pat:
            self._animator.squash(now, "click")
            self._refresh(now)
            self.clicked.emit()
            if double:
                self.double_clicked.emit()

    def contextMenuEvent(self, e) -> None:
        self.menu_requested.emit(e.globalPos())

    # ---- 原地动作 ----
    def set_calm(self, calm: bool) -> None:
        self._animator.calm = calm

    def set_activity(self, level: str) -> None:
        self._animator.activity_level = level

    @property
    def motion_active(self) -> bool:
        return self._jump_start is not None

    @property
    def idle_motion_active(self) -> bool:
        return self._jump_start is not None and self._automatic_jump

    @property
    def is_pressed(self) -> bool:
        return self._press_global is not None

    def stop_motion(self) -> None:
        self._jump_start = None
        self._jump_offset = 0.0
        self._refresh(self._clock())

    def jump(self, *, automatic: bool = False) -> None:
        if self._dragging or self._falling:
            return
        self.stop_motion()
        self._automatic_jump = automatic
        self._jump_start = self._clock()
        self.advance_to(self._jump_start)

    def consume_shaken(self) -> bool:
        shaken = self._shake.shaken
        self._shake.reset(0.0)
        return shaken

    # ---- 下落 ----
    def bounce(self) -> None:
        """跳一下（催你回来用）：复用点击的压扁回弹。"""
        now = self._clock()
        self._animator.squash(now, "click")
        self._refresh(now)

    def start_fall(self) -> None:
        avail = self._screen_avail(self.geometry().center())
        x, floor_y = landing_geometry(
            avail, self.width(), self.height(), self.x(), MARGIN_X, MARGIN_BOTTOM
        )
        self._fall_floor = floor_y
        self.move(x, min(self.y(), floor_y))  # 在底边以下就先拉回底边
        self._fy = float(self.y())
        self._vy = 0.0
        self._falling = True
        self._last_tick = self._clock()
        self._fall_start = self._last_tick
        self._fall_y0 = self._fy
        self.advance_to(self._last_tick)

    def _stop_fall(self) -> None:
        self._falling = False

    def _fall_step(self, now: float) -> None:
        elapsed = max(0.0, now - self._fall_start)
        # 重力的二次加速曲线：解析求位置，不因掉帧截断 dt 而变慢。
        self._vy = GRAVITY * elapsed
        self._fy = self._fall_y0 + 0.5 * GRAVITY * elapsed ** 2
        if self._fy >= self._fall_floor:
            self._fy = float(self._fall_floor)
            self.move(self.x(), self._fall_floor)
            self._stop_fall()
            landed_at = self._fall_start + math.sqrt(max(0.0, 2 * (self._fall_floor - self._fall_y0) / GRAVITY))
            if self._drag_active:
                self._drag_active = False
                self._drag_playback = None
                self.drag_finished.emit()
            self._animator.squash(landed_at, "land")
            return
        self.move(self.x(), round(self._fy))

    @property
    def is_falling(self) -> bool:
        return self._falling

    @property
    def is_dragging(self) -> bool:
        return self._dragging
