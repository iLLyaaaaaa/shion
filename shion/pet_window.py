"""透明置顶的桌宠窗口：显示精灵、动画、拖动、松手重力下落。

窗口画布比精灵大一圈（留边），这样倾斜、晃动时不会被裁掉。
脚底中心固定在画布底边的中点，所有变换都以它为锚点。
"""
from __future__ import annotations

import math
import time
from dataclasses import replace
from pathlib import Path
from typing import Callable

import numpy as np
from PySide6.QtCore import QPoint, QRect, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import (
    QBitmap, QGuiApplication, QImage, QPainter, QPixmap, QRegion, QTransform,
)
from PySide6.QtWidgets import QWidget

from shion.animator import Animator, Frame
from shion.behavior import (
    JUMP_AIR_DURATION, JUMP_CROUCH_DURATION, JUMP_DURATION, JUMP_HEIGHT,
    LEGACY_JUMP_DURATION, LEGACY_JUMP_HEIGHT, WALK_BOB_FRAMES, WALK_BOB_HEIGHT,
    ShakeTracker, Walk,
)

SPRITE_DIR = Path(__file__).resolve().parent.parent / "assets" / "sprites"
STATES = [
    "idle", "blink", "happy", "proud", "stop", "dizzy",
    "working", "done", "sleep", "drag", "neglect1", "neglect2",
]
SEQUENCES = {
    "walk": tuple(f"walk_{i}" for i in range(1, 5)),
    "jump": ("jump_1", "jump_2"),
}

DEFAULT_HEIGHT = 200
HEAD_FRAC = 0.45  # 精灵上方多少比例算头部（摸头判定区）
MARGIN_X = 64  # 画布左右留边（倾斜 12° 时头部偏移约 50px）
MARGIN_TOP = round(JUMP_HEIGHT) + 8  # 给原地跳留出空间
MARGIN_BOTTOM = 6  # 倾斜时一只脚会往下沉，留出空间不被裁掉
MASK_GROW = 4  # 遮罩向外扩的像素，吸收角度/缩放量化的误差
MASK_CACHE_MAX = 64
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
    hovered = Signal()  # 鼠标进入（只唤醒）
    patted = Signal()  # 在头部左右移动，每累计 40px 一次
    clicked = Signal()  # 按下到松开几乎没动
    double_clicked = Signal()  # 在对应的 clicked 之后发出
    drag_started = Signal()
    drag_finished = Signal()  # 松手后落地时发出
    menu_requested = Signal(QPoint)  # 全局坐标
    moved = Signal()  # 窗口位置变了（气泡跟随用）
    pressed = Signal()  # 左键按下即中断自主运动
    motion_finished = Signal()  # 自主行走结束/中断后保存位置

    def __init__(
        self,
        height: int = DEFAULT_HEIGHT,
        clock: Callable[[], float] = time.perf_counter,
        autostart: bool = True,
    ):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("Shion")
        self.setMouseTracking(True)

        self._clock = clock
        self._height = height
        self._pixmaps: dict[str, QPixmap] = {}
        self._mirrored_pixmaps: dict[str, QPixmap] = {}
        self._sequences: dict[str, tuple[str, ...]] = {}
        self._sw = 0  # 精灵逻辑宽高
        self._sh = 0
        self._load_sprites()
        self.setFixedSize(self._sw + 2 * MARGIN_X, self._sh + MARGIN_TOP + MARGIN_BOTTOM)

        self._animator = Animator()
        self._frame = Frame("idle")
        self._mask_cache: dict[tuple, QRegion] = {}
        self._mask_key: tuple | None = None

        # 拖动 / 下落
        self._press_global: QPoint | None = None
        self._grab_offset = QPoint()
        self._dragging = False
        self._last_drag_x = 0
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
        self._walk: Walk | None = None
        self._walk_floor = 0
        self._jump_start: float | None = None
        self._jump_framed = False
        self._automatic_jump = False
        self._jump_offset = 0.0
        self._facing = 1  # 原图朝向；+1 向右，-1 为镜像

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._on_timer)

        self.set_state("idle")
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
        self._mask_cache.clear()
        self._mask_key = None
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

    def head_anchor(self) -> QPoint:
        """头顶中心（全局坐标），给爱心和提示定位。"""
        return self.mapToGlobal(QPoint(self.width() // 2, MARGIN_TOP + int(self._sh * 0.08)))

    def body_rect(self) -> tuple[int, int, int, int]:
        """精灵本体的屏幕矩形 (x, y, w, h)，不含留边。"""
        return (self.x() + MARGIN_X, self.y() + MARGIN_TOP, self._sw, self._sh)

    def moveEvent(self, e) -> None:
        super().moveEvent(e)
        self.moved.emit()

    def _is_head(self, pos: QPoint) -> bool:
        """鼠标是否在精灵上方 45%（按未变换的精灵坐标）。"""
        sx = pos.x() - MARGIN_X
        sy = pos.y() - MARGIN_TOP
        return 0 <= sx < self._sw and 0 <= sy < self._sh * HEAD_FRAC

    def _load_sprites(self) -> None:
        screen = QGuiApplication.primaryScreen()
        dpr = screen.devicePixelRatio() if screen else 1.0
        self._pixmaps.clear()
        self._mirrored_pixmaps.clear()
        self._sequences.clear()

        def cache(name: str, src: QPixmap) -> None:
            pix = src.scaledToHeight(round(self._height * dpr), Qt.SmoothTransformation)
            pix.setDevicePixelRatio(dpr)
            self._pixmaps[name] = pix
            mirrored = pix.transformed(QTransform().scale(-1, 1), Qt.FastTransformation)
            mirrored.setDevicePixelRatio(dpr)
            self._mirrored_pixmaps[name] = mirrored

        canvas = None
        for name in STATES:
            src = QPixmap(str(SPRITE_DIR / f"{name}.png"))
            if src.isNull():
                raise FileNotFoundError(SPRITE_DIR / f"{name}.png")
            cache(name, src)
            if name == "idle":
                canvas = src.size()
                self._sw = round(self._pixmaps[name].width() / dpr)
                self._sh = round(self._pixmaps[name].height() / dpr)
        for group, names in SEQUENCES.items():
            sources = [QPixmap(str(SPRITE_DIR / f"{name}.png")) for name in names]
            # 可选帧必须整组齐全且同画布；缺图或坏图沿用原来的程序动画。
            if any(src.isNull() or src.size() != canvas for src in sources):
                continue
            for name, src in zip(names, sources):
                cache(name, src)
            self._sequences[group] = names

    @property
    def sprite_size(self) -> tuple[int, int]:
        return self._sw, self._sh

    def set_state(self, name: str, *, animate: bool = True) -> None:
        if name not in STATES:
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
        p.save()
        p.translate(self.width() / 2, self.height() - MARGIN_BOTTOM - self._jump_offset)
        p.rotate(f.angle)  # 倾斜是屏幕方向，镜像不应反转拖动速度的倾斜方向
        p.scale(f.sx, f.sy)
        pixmaps = self._pixmaps if self._facing > 0 else self._mirrored_pixmaps
        target = QRectF(-self._sw / 2, -self._sh, self._sw, self._sh)
        layers = f.layers or ((f.sprite, 1.0),)
        if all(weight == 1.0 for _, weight in layers):
            for name, _ in layers:
                pix = pixmaps[name]
                p.drawPixmap(target, pix, QRectF(pix.rect()))
        else:
            # 在预乘 RGBA 上加权，避免 SourceOver 使重叠身体闪透。
            # numpy 是项目现有依赖；整数权重总和固定，保持不透明像素 alpha=255。
            pix = pixmaps[f.sprite]
            accum = np.zeros((pix.height(), pix.width() * 4), dtype=np.uint32)
            remaining = 65536
            for index, (name, weight) in enumerate(layers):
                iw = remaining if index == len(layers) - 1 else min(remaining, round(weight * 65536))
                remaining -= iw
                src = pixmaps[name].toImage().convertToFormat(QImage.Format_ARGB32_Premultiplied)
                pixels = np.frombuffer(src.constBits(), dtype=np.uint8).reshape(src.height(), src.bytesPerLine())
                accum += pixels.astype(np.uint32) * iw
            pixels = ((accum + 32768) >> 16).astype(np.uint8)
            mix = QImage(pixels.data, pix.width(), pix.height(), pix.width() * 4, QImage.Format_ARGB32_Premultiplied).copy()
            mix.setDevicePixelRatio(pix.devicePixelRatio())
            p.drawImage(target, mix, QRectF(mix.rect()))
        p.restore()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHints(QPainter.SmoothPixmapTransform | QPainter.Antialiasing)
        self._draw_sprite(p, self._frame)

    def render_frame(self) -> QImage:
        """把当前帧画进一张透明 QImage（不受遮罩裁剪，截图和测试用）。"""
        img = QImage(self.size(), QImage.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        p.setRenderHints(QPainter.SmoothPixmapTransform | QPainter.Antialiasing)
        self._draw_sprite(p, self._frame)
        p.end()
        return img

    def _mask_for(self, f: Frame) -> QRegion:
        """遮罩 = 当前画出的不透明像素向外扩 MASK_GROW px。只有遮罩里的地方响应鼠标。"""
        names = tuple(sorted(name for name, weight in f.layers or ((f.sprite, 1.0),) if weight > 0))
        key = (names, round(f.angle), round(f.sx, 2), round(f.sy, 2), self._facing, round(self._jump_offset))
        if key == self._mask_key:
            return self._mask_cache[key]
        region = self._mask_cache.get(key)
        if region is None:
            q = Frame(f.sprite, key[2], key[3], float(key[1]), tuple((name, 1.0) for name in names))
            img = QImage(self.size(), QImage.Format_ARGB32_Premultiplied)
            img.fill(0)
            p = QPainter(img)
            p.setRenderHints(QPainter.SmoothPixmapTransform | QPainter.Antialiasing)
            self._draw_sprite(p, q)
            p.end()
            # 保留每个非透明像素，避免 alpha 抖动阈值吃掉细小半透明轮廓。
            base = QRegion(QBitmap.fromImage(img.createMaskFromColor(0, Qt.MaskInColor)))
            region = QRegion(base)
            g = MASK_GROW
            # 只绘制一次，把位图区域平移合并；避免每次遮罩重画 13 次精灵。
            for dx, dy in ((g, 0), (-g, 0), (0, g), (0, -g),
                           (g, g), (-g, g), (g, -g), (-g, -g),
                           (g // 2, 0), (-g // 2, 0), (0, g // 2), (0, -g // 2)):
                region |= base.translated(dx, dy)
            region &= QRegion(self.rect())
            if len(self._mask_cache) >= MASK_CACHE_MAX:
                self._mask_cache.clear()
            self._mask_cache[key] = region
        self._mask_key = key
        return region

    def _refresh(self, now: float) -> None:
        f = self._animator.frame(now)
        if self._walk is not None and "walk" in self._sequences:
            f = Frame(self._sequence_sprite("walk", now - self._walk.start, self._walk.frame_seconds))
        elif self._jump_start is not None and self._jump_framed:
            elapsed = max(0.0, now - self._jump_start)
            f = Frame(self._sequences["jump"][0 if elapsed + 1e-9 < JUMP_CROUCH_DURATION else 1])
        # 量化到肉眼分辨不出的精度：呼吸这类缓慢变化不必每帧重绘
        f = replace(f, sx=round(f.sx, 3), sy=round(f.sy, 3), angle=round(f.angle, 2))
        if (f == self._frame and self._mask_key is not None
                and self._mask_key[4:] == (self._facing, round(self._jump_offset))):
            return
        self._frame = f
        old_key = self._mask_key
        region = self._mask_for(f)
        if self._mask_key != old_key:
            self.setMask(region)
        self.update()

    def _sequence_sprite(self, group: str, elapsed: float, frame_seconds: float) -> str:
        frames = self._sequences[group]
        index = int(max(0.0, elapsed) / frame_seconds + 1e-9) % len(frames)
        return frames[index]

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
        if self._walk is not None:
            x, jump, direction, finished = self._walk.sample(now)
            self._facing = direction
            self.move(round(x), self._walk_floor)
            self._jump_offset = jump
            if "walk" in self._sequences and not finished:
                elapsed = max(0.0, now - self._walk.start)
                period = self._walk.frame_seconds * WALK_BOB_FRAMES
                self._jump_offset = WALK_BOB_HEIGHT * abs(math.sin(math.pi * elapsed / period))
            if finished:
                self._walk = None
                self._jump_offset = 0.0
                self.motion_finished.emit()
        elif self._jump_start is not None:
            duration = JUMP_DURATION if self._jump_framed else LEGACY_JUMP_DURATION
            crouch = JUMP_CROUCH_DURATION if self._jump_framed else 0.0
            air = JUMP_AIR_DURATION if self._jump_framed else LEGACY_JUMP_DURATION
            height = JUMP_HEIGHT if self._jump_framed else LEGACY_JUMP_HEIGHT
            elapsed = max(0.0, now - self._jump_start)
            p = max(0.0, min(1.0, (elapsed - crouch) / air))
            self._jump_offset = height * math.sin(math.pi * p)
            if elapsed + 1e-9 >= duration:
                if self._jump_framed:
                    self._animator.squash(self._jump_start + duration, "land")
                self._jump_start = None
                self._jump_offset = 0.0
        if self._dragging and dt > 0:
            vx = (self.x() - self._last_drag_x) / dt
            self._last_drag_x = self.x()
            self._animator.feed_velocity(vx, now)
        if self._falling:
            self._fall_step(now)
        self._refresh(now)

    # ---- 鼠标 ----
    def enterEvent(self, _e) -> None:
        self.hovered.emit()

    def _update_hover_cursor(self, pos: QPoint) -> None:
        if self._is_head(pos):
            self.setCursor(Qt.OpenHandCursor)
        else:
            self.unsetCursor()

    def mousePressEvent(self, e) -> None:
        if e.button() != Qt.LeftButton:
            return
        self.stop_motion()
        self.pressed.emit()
        self._caught_fall = self._falling
        self._stop_fall()
        self._press_global = e.globalPosition().toPoint()
        self._grab_offset = self._press_global - self.pos()
        self._dragging = False
        self._moved = False
        self._pat_mode = self._is_head(e.position().toPoint())
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
        if not self._moved:
            d = gp - self._press_global
            if math.hypot(d.x(), d.y()) <= DRAG_THRESHOLD:
                if self._pat_mode:
                    self._pat_step(gp)
                return
            self._moved = True
        if self._pat_mode:
            self._pat_step(gp)
            return
        if not self._dragging:
            self._dragging = True
            now = self._clock()
            self._shake.reset(self._press_global.x())
            self._animator.set_drag(True, now)
            self._last_drag_x = self.x()
            self._last_tick = now
            self.setCursor(Qt.ClosedHandCursor)
            if not self._drag_active:
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
        self._press_global = None
        self._dragging = False
        self._pat_mode = False
        self._double = False
        self._caught_fall = False
        self._animator.set_drag(False, self._clock())
        self._update_hover_cursor(e.position().toPoint())
        now = self._clock()
        if was_dragging:
            self.start_fall()
        elif caught:
            self.start_fall()  # 抓住下落中的桌宠又松开：继续落
        elif not was_pat:
            self._animator.squash(now, "click")
            self._refresh(now)
            self.clicked.emit()
            if double:
                self.double_clicked.emit()

    def contextMenuEvent(self, e) -> None:
        self.stop_motion()
        self.menu_requested.emit(e.globalPos())

    # ---- 原地动作 / 沿任务栏行走 ----
    @property
    def facing(self) -> int:
        return self._facing

    def face(self, direction: int) -> None:
        self._facing = 1 if direction >= 0 else -1
        self._refresh(self._clock())

    def turn(self) -> None:
        self.face(-self._facing)

    def set_calm(self, calm: bool) -> None:
        self._animator.calm = calm

    @property
    def motion_active(self) -> bool:
        return self._walk is not None or self._jump_start is not None

    @property
    def idle_motion_active(self) -> bool:
        return self._jump_start is not None and self._automatic_jump

    @property
    def is_pressed(self) -> bool:
        return self._press_global is not None

    def stop_motion(self) -> None:
        walking = self._walk is not None
        self._walk = None
        self._jump_start = None
        self._jump_offset = 0.0
        self._refresh(self._clock())
        if walking:
            self.motion_finished.emit()

    def jump(self, *, automatic: bool = False) -> None:
        if self._dragging or self._falling:
            return
        self.stop_motion()
        self._automatic_jump = automatic
        self._jump_framed = "jump" in self._sequences
        self._jump_start = self._clock()
        self.advance_to(self._jump_start)

    def walk(self, *, cross: bool = False, rng=None) -> None:
        if self._dragging or self._falling:
            return
        self.stop_motion()
        self.snap_to_floor()
        avail = self._screen_avail(self.geometry().center())
        lo = avail.left() - MARGIN_X
        hi = avail.right() + 1 - self.width() + MARGIN_X
        self._walk_floor = self.y()
        self._walk = Walk(self.x(), lo, hi, self._clock(), cross=cross, rng=rng)
        self.advance_to(self._clock())

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
