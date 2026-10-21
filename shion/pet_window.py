"""透明置顶的桌宠窗口：显示精灵、动画、拖动、原地停放或重力下落。

窗口画布比精灵大一圈（留边），这样倾斜、晃动时不会被裁掉。
脚底中心固定在画布底边的中点，所有变换都以它为锚点。
"""
from __future__ import annotations

import math
import os
import re
import time
from collections import OrderedDict
from dataclasses import replace
from pathlib import Path
from typing import Callable

import numpy as np
from PySide6.QtCore import QPoint, QRect, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import (
    QBitmap, QGuiApplication, QImage, QPainter, QPixmap, QRegion,
)
from PySide6.QtWidgets import QWidget

from shion.animator import Animator, Frame
from shion.behavior import (
    JUMP_DURATION, JUMP_HEIGHT,
    LEGACY_JUMP_DURATION, LEGACY_JUMP_HEIGHT,
    SHAKE_WINDOW, DragPlayback, ShakeTracker, jump_sample, TickleGesture,
    TURN_FRAME_SECONDS, FACE_SECONDS, CHEEK_RELEASE_SECONDS, CHEEK_LIFT_DISTANCE,
    TICKLE_STOP_SECONDS, TICKLE_FRAME_SECONDS, TICKLE_TWIST_DEGREES,
    TICKLE_TWIST_PERIOD, TICKLE_SPEECH_SECONDS, BELLY_LIFT_DISTANCE, TICKLE_MOVE_DISTANCE,
    ReleaseVelocity, RELEASE_FAST_SPEED,
)

SPRITE_DIR = Path(__file__).resolve().parent.parent / "assets" / "sprites"
STATES = [
    "idle", "blink", "happy", "proud", "stop", "dizzy",
    "working", "done", "sleep", "drag", "neglect1", "neglect2",
]
PROP_STATES = ("bed", "desk")
SEQUENCE_GROUPS = ("jump", "drag", "turn", "tickle", "cheek", "bed", "desk")
EXACT_SEQUENCES = {"turn": 8, "tickle": 3, "cheek": 3, "bed": 2, "desk": 3}

DEFAULT_HEIGHT = 200
# 依据 idle 448×512 画布测量；不包含窗口留边，各尺寸使用相同比例。
HEAD_FRAC = 0.38
CHEEK_BOTTOM_FRAC = 0.56
BELLY_TOP_FRAC = 0.60
BELLY_BOTTOM_FRAC = 0.78
BELLY_LEFT_FRAC = 0.32
BELLY_RIGHT_FRAC = 0.68
MARGIN_X = 64  # 画布左右留边（倾斜 12° 时头部偏移约 50px）
MARGIN_TOP = round(JUMP_HEIGHT) + 8  # 给原地跳留出空间
MARGIN_BOTTOM = 6  # 倾斜时一只脚会往下沉，留出空间不被裁掉
MASK_GROW = 4  # 遮罩向外扩的像素，吸收角度/缩放量化的误差
MASK_CACHE_MAX = 64
MASK_ANGLE_STEP = 1.0
MASK_SCALE_STEP = 0.01
DRAW_SCALE_DIGITS = 3
DRAW_ANGLE_DIGITS = 2
PAT_DISTANCE = 40  # px，摸头累计移动多少算一次
DRAG_THRESHOLD = 6  # px，超过才算拖动
GRAVITY = 2400.0  # px/s²
FRAME_MS = 16
ACTION_FADE_SECONDS = 0.100  # 仅 idle（含 blink）与独立动作帧的进出边界


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
    ):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("Shion")
        self.setMouseTracking(True)

        self._clock = clock
        self._fps_overlay = None
        self._pause_badge = None  # 暂停文字标签，第一次要显示时才建
        self._height = height
        self._pixmaps: dict[str, QPixmap] = {}
        self._sequences: dict[str, tuple[str, ...]] = {}
        self._sw = 0  # 精灵逻辑宽高
        self._sh = 0
        self._load_sprites()
        self.setFixedSize(self._sw + 2 * MARGIN_X, self._sh + MARGIN_TOP + MARGIN_BOTTOM)

        self._animator = Animator()
        self._frame = Frame("idle")
        self._action_fade: tuple[float, tuple[tuple[str, float], ...]] | None = None
        self._mask_cache: OrderedDict[tuple, QRegion] = OrderedDict()
        self._mask_key: tuple | None = None

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
        self._turn_start: float | None = None
        self._pose: str | None = None
        self._pose_until = 0.0
        self._automatic_pose = False
        self._cheek_mode = False
        self._cheek_pulling = False
        self._belly_mode = False
        self._tickle = TickleGesture()
        self._tickle_start: float | None = None
        self._tickle_last = 0.0
        self._tickle_said = 0.0
        self._rub_last = QPoint()
        self._jump_start: float | None = None
        self._jump_framed = False
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
        self._mask_cache.clear()
        self._mask_key = None
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

    def moveEvent(self, e) -> None:
        super().moveEvent(e)
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
        if self._fps_overlay is not None:
            self._fps_overlay.resume()
        if self._pause_badge is not None:
            self._pause_badge.refresh()

    def hideEvent(self, e) -> None:
        if self._fps_overlay is not None:
            self._fps_overlay.pause()
        if self._pause_badge is not None:
            self._pause_badge.hide()
        super().hideEvent(e)

    def closeEvent(self, e) -> None:
        self._timer.stop()
        if self._fps_overlay is not None:
            self._fps_overlay.pause()
        if self._pause_badge is not None:
            self._pause_badge.hide()
        super().closeEvent(e)

    def _is_head(self, pos: QPoint) -> bool:
        """按 idle 画布坐标划区，忽略窗口留边。"""
        return self._hit_zone(pos) == "head"

    def _hit_zone(self, pos: QPoint) -> str:
        sx = pos.x() - MARGIN_X
        sy = pos.y() - MARGIN_TOP
        if not (0 <= sx < self._sw and 0 <= sy < self._sh):
            return "outside"
        if sy < self._sh * HEAD_FRAC:
            return "head"
        if sy < self._sh * CHEEK_BOTTOM_FRAC:
            return "cheek"
        if (self._sh * BELLY_TOP_FRAC <= sy < self._sh * BELLY_BOTTOM_FRAC
                and self._sw * BELLY_LEFT_FRAC <= sx < self._sw * BELLY_RIGHT_FRAC):
            return "belly"
        return "body"

    def _load_sprites(self) -> None:
        screen = QGuiApplication.primaryScreen()
        dpr = screen.devicePixelRatio() if screen else 1.0
        self._pixmaps.clear()
        self._sequences.clear()

        def cache(name: str, src: QPixmap) -> None:
            pix = src.scaledToHeight(round(self._height * dpr), Qt.SmoothTransformation)
            pix.setDevicePixelRatio(dpr)
            self._pixmaps[name] = pix

        canvas = None
        for name in STATES:
            src = QPixmap(str(SPRITE_DIR / f"{name}.png"))
            if src.isNull():
                raise FileNotFoundError(SPRITE_DIR / f"{name}.png")
            cache(name, src)
            if name == "idle":
                canvas = src.size()
                self._sw = round(self._pixmaps[name].width() / dpr)
                self.normal_width = self._sw
                self._sh = round(self._pixmaps[name].height() / dpr)
        for group in SEQUENCE_GROUPS:
            numbered = sorted((int(match[1]), path.stem)
                              for path in SPRITE_DIR.glob(f"{group}_*.png")
                              if (match := re.fullmatch(rf"{group}_([1-9]\d*)", path.stem)))
            if not numbered or any(number != i for i, (number, _) in enumerate(numbered, 1)):
                continue
            if group in EXACT_SEQUENCES and len(numbered) != EXACT_SEQUENCES[group]:
                continue
            names = tuple(name for _, name in numbered)
            sources = [QPixmap(str(SPRITE_DIR / f"{name}.png")) for name in names]
            # 可选帧必须整组齐全且同画布；缺图或坏图沿用原来的程序动画。
            expected_canvas = sources[0].size()
            if (any(src.isNull() or src.size() != expected_canvas for src in sources)
                    or expected_canvas.height() != canvas.height()):
                continue
            for name, src in zip(names, sources):
                cache(name, src)
            self._sequences[group] = names

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
        p.save()
        p.translate(self.width() / 2, self.height() - MARGIN_BOTTOM - self._jump_offset)
        p.rotate(f.angle)
        p.scale(f.sx, f.sy)
        pixmaps = self._pixmaps
        layers = f.layers or ((f.sprite, 1.0),)
        dpr = pixmaps[f.sprite].devicePixelRatio()
        pixel_width = max(pixmaps[name].width() for name, _ in layers)
        pixel_height = max(pixmaps[name].height() for name, _ in layers)
        target = QRectF(-pixel_width / dpr / 2, -pixel_height / dpr, pixel_width / dpr, pixel_height / dpr)
        if all(weight == 1.0 for _, weight in layers):
            for name, _ in layers:
                pix = pixmaps[name]
                r = QRectF(-pix.width() / dpr / 2, -pix.height() / dpr, pix.width() / dpr, pix.height() / dpr)
                p.drawPixmap(r, pix, QRectF(pix.rect()))
        else:
            # 在预乘 RGBA 上加权，避免 SourceOver 使重叠身体闪透。
            # numpy 是项目现有依赖；整数权重总和固定，保持不透明像素 alpha=255。
            pix = pixmaps[f.sprite]
            accum = np.zeros((pixel_height, pixel_width, 4), dtype=np.uint32)
            remaining = 65536
            for index, (name, weight) in enumerate(layers):
                iw = remaining if index == len(layers) - 1 else min(remaining, round(weight * 65536))
                remaining -= iw
                src = pixmaps[name].toImage().convertToFormat(QImage.Format_ARGB32_Premultiplied)
                pixels = np.frombuffer(src.constBits(), dtype=np.uint8).reshape(src.height(), src.bytesPerLine() // 4, 4)[:, :src.width()]
                left = (pixel_width - src.width()) // 2
                accum[pixel_height-src.height():, left:left+src.width()] += pixels.astype(np.uint32) * iw
            pixels = ((accum + 32768) >> 16).astype(np.uint8)
            mix = QImage(pixels.data, pixel_width, pixel_height, pixel_width * 4, QImage.Format_ARGB32_Premultiplied).copy()
            mix.setDevicePixelRatio(pix.devicePixelRatio())
            p.drawImage(target, mix, QRectF(mix.rect()))
        p.restore()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHints(QPainter.SmoothPixmapTransform | QPainter.Antialiasing)
        self._draw_sprite(p, self._frame)
        p.end()
        if self._fps_overlay is not None:
            self._fps_overlay.counter.record()

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
        key = (names, round(f.angle / MASK_ANGLE_STEP) * MASK_ANGLE_STEP,
               round(f.sx / MASK_SCALE_STEP) * MASK_SCALE_STEP,
               round(f.sy / MASK_SCALE_STEP) * MASK_SCALE_STEP, round(self._jump_offset))
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
                self._mask_cache.popitem(last=False)
            self._mask_cache[key] = region
        self._mask_cache.move_to_end(key)
        self._mask_key = key
        return region

    def _refresh(self, now: float) -> None:
        self._animator.idle_enabled = not (self.motion_active or self._dragging or self._falling
                                          or self.is_pressed or self._drag_playback is not None)
        f = self._animator.frame(now)
        def available(name):
            if name.startswith("bed_") and "bed" not in self._sequences:
                return "sleep"
            if name.startswith("desk_") and "desk" not in self._sequences:
                return "neglect1"
            return name
        f = replace(f, sprite=available(f.sprite), layers=tuple((available(n), w) for n, w in f.layers))
        f = self._action_frame(now, f)
        f = self._blend_action(now, f)
        # 淡化的所有图按各自原宽绘制；切换画布只移动左边缘，脚底中心不动。
        # 目标层在 alpha=0 的起点也提前占位，避免下一帧才撑开宽画布。
        names = [f.sprite] + [name for name, _ in f.layers]
        if self.sprite_name in self._pixmaps:
            names.append(self.sprite_name)
        if self.sprite_name in PROP_STATES and self.sprite_name in self._sequences:
            names.append(self._sequences[self.sprite_name][0])
        width = max(round(self._pixmaps[n].width() / self._pixmaps[n].devicePixelRatio()) for n in names)
        if width != self._sw:
            feet_x = self.x() + self.width() / 2
            old_pos = self.pos()
            self._sw = width
            self.setFixedSize(width + 2 * MARGIN_X, self.height())
            self.move(round(feet_x - self.width() / 2), self.y())
            self._mask_cache.clear()
            self._mask_key = None
            self.clamp_position()
            if self._press_global is not None:
                self._grab_offset += old_pos - self.pos()
            self.moved.emit()  # 即使夹边后左上角相同，气泡也要重新定位
        # 量化到肉眼分辨不出的精度：呼吸这类缓慢变化不必每帧重绘
        f = replace(f, sx=round(f.sx, DRAW_SCALE_DIGITS), sy=round(f.sy, DRAW_SCALE_DIGITS),
                    angle=round(f.angle, DRAW_ANGLE_DIGITS))
        if (f == self._frame and self._mask_key is not None
                and self._mask_key[4] == round(self._jump_offset)):
            return
        self._frame = f
        old_key = self._mask_key
        region = self._mask_for(f)
        if self._mask_key != old_key:
            self.setMask(region)
        self.update()
        if self._fps_overlay is not None:
            self._fps_overlay.follow()
        if self._pause_badge is not None:
            self._pause_badge.follow()

    def _action_frame(self, now: float, f: Frame) -> Frame:
        """只取动作帧；不推进时间线，供结束时采样预定的最后一帧。"""
        if self._jump_start is not None and self._jump_framed:
            elapsed = max(0.0, now - self._jump_start)
            _, progress, sy = jump_sample(elapsed)
            names = self._sequences["jump"]
            index = min(len(names) - 1, int(progress * len(names) + 1e-9))
            f = Frame(names[index], sx=1 / math.sqrt(sy), sy=sy)
        elif self._drag_playback is not None and "drag" in self._sequences:
            names = self._sequences["drag"]
            name = names[int(self._drag_playback.phase + 1e-9) % len(names)]
            # 保留拖动倾斜，但不对序列帧做底层表情交叉淡化。
            f = replace(f, sprite=name, layers=())
        elif self._tickle_start is not None:
            elapsed = max(0.0, now - self._tickle_start)
            name = (self._sequence_sprite("tickle", elapsed, TICKLE_FRAME_SECONDS)
                    if "tickle" in self._sequences else "happy")
            f = Frame(name, angle=TICKLE_TWIST_DEGREES * math.sin(2 * math.pi * elapsed / TICKLE_TWIST_PERIOD))
        elif self._pose is not None:
            f = Frame(self._pose)
        elif self._turn_start is not None:
            names = self._sequences["turn"]
            index = min(len(names) - 1, int(max(0.0, now - self._turn_start) / TURN_FRAME_SECONDS + 1e-9))
            f = Frame(names[index])
        return f

    def _blend_action(self, now: float, f: Frame) -> Frame:
        """动作边界的透明度混合；沿用目标帧的动作姿态，不增加压扁。"""
        if self.sprite_name != "idle" or self._dragging or self._falling or self._drag_playback is not None:
            self._action_fade = None
        if self._action_fade is None:
            return f
        start, source = self._action_fade
        alpha = max(0.0, min(1.0, (now - start) / ACTION_FADE_SECONDS))
        if alpha >= 1.0 - 1e-9:
            self._action_fade = None
            return f
        weights: dict[str, float] = {}
        for layers, factor in ((source, 1 - alpha), (f.layers or ((f.sprite, 1.0),), alpha)):
            for name, weight in layers:
                weights[name] = weights.get(name, 0.0) + weight * factor
        return replace(f, layers=tuple((name, weight) for name, weight in weights.items() if weight > 0))

    def _begin_action_fade(self, now: float, source: Frame | None = None) -> None:
        """从当前混合接续；自然结束传预定时刻的末帧，避免依赖上一绘制帧。"""
        if self.sprite_name != "idle" or self._dragging or self._falling or self._drag_playback is not None:
            self._action_fade = None
            return
        if source is None:
            source = self._blend_action(now, self._action_frame(now, self._animator.frame(now)))
        self._action_fade = (now, source.layers or ((source.sprite, 1.0),))

    def _finish_action_fade(self, at: float) -> None:
        source = self._blend_action(at, self._action_frame(at, self._animator.frame(at)))
        self._begin_action_fade(at, source)

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
        if self._turn_start is not None and now + 1e-9 >= self._turn_start + len(self._sequences["turn"]) * TURN_FRAME_SECONDS:
            self._finish_action_fade(self._turn_start + len(self._sequences["turn"]) * TURN_FRAME_SECONDS)
            self._turn_start = None
        if self._pose is not None and not self._cheek_pulling and now + 1e-9 >= self._pose_until:
            self._finish_action_fade(self._pose_until)
            self._pose = None
        if self._tickle_start is not None:
            if now - self._tickle_last + 1e-9 >= TICKLE_STOP_SECONDS:
                self._end_tickle(speak=True, at=self._tickle_last + TICKLE_STOP_SECONDS)
            elif now - self._tickle_said >= TICKLE_SPEECH_SECONDS:
                self._tickle_said = now
                self.gesture.emit("tickle")
        if self._jump_start is not None:
            duration = JUMP_DURATION if self._jump_framed else LEGACY_JUMP_DURATION
            elapsed = max(0.0, now - self._jump_start)
            if self._jump_framed:
                self._jump_offset = jump_sample(elapsed)[0]
            else:
                p = max(0.0, min(1.0, elapsed / LEGACY_JUMP_DURATION))
                self._jump_offset = LEGACY_JUMP_HEIGHT * math.sin(math.pi * p)
            if elapsed + 1e-9 >= duration:
                if self._jump_framed:
                    self._finish_action_fade(self._jump_start + duration)
                    self._animator.squash(self._jump_start + duration, "jump_land")
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
        self._release_velocity = ReleaseVelocity()
        self._release_velocity.feed(self._clock(), self._press_global.x(), self._press_global.y())
        self._grab_offset = self._press_global - self.pos()
        self._dragging = False
        self._moved = False
        self._pat_mode = self._is_head(e.position().toPoint())
        zone = self._hit_zone(e.position().toPoint())
        self._cheek_mode = zone == "cheek" and not self._caught_fall
        self._cheek_pulling = False
        self._belly_mode = zone == "belly" and not self._caught_fall
        self._rub_last = QPoint(self._press_global)
        self._tickle.begin_rub(self._press_global.x())
        if not self._belly_mode:
            self._end_tickle()
            self._tickle.clicks.clear()
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
                if self._pat_mode:
                    self._pat_step(gp)
                if not self._belly_mode:
                    return
            else:
                self._moved = True
        if self._pat_mode:
            self._pat_step(gp)
            return
        d = gp - self._press_global
        distance = math.hypot(d.x(), d.y())
        if self._cheek_mode:
            if distance <= CHEEK_LIFT_DISTANCE:
                if abs(d.x()) > DRAG_THRESHOLD:
                    first = not self._cheek_pulling
                    if first:
                        self._begin_action_fade(self._clock())
                    self._cheek_pulling = True
                    self._pose = self._gesture_sprite("cheek", 1 if d.x() > 0 else 2, "stop")
                    if first:
                        self.gesture.emit("cheek_pull")
                    self._refresh(self._clock())
                return
            self._cheek_mode = self._cheek_pulling = False
            self._pose = None
        if self._belly_mode:
            if distance <= BELLY_LIFT_DISTANCE:
                movement = gp - self._rub_last
                if math.hypot(movement.x(), movement.y()) >= TICKLE_MOVE_DISTANCE:
                    self._rub_last = QPoint(gp)
                    now = self._clock()
                    self.gesture.emit("belly")
                    rub = self._tickle.rub(gp.x(), now)
                    if rub or self._tickle_start is not None:
                        self._feed_tickle(now)
                return
            self._belly_mode = False
        self._end_tickle()
        self._tickle.clicks.clear()
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

    def _gesture_sprite(self, group: str, index: int, fallback: str) -> str:
        names = self._sequences.get(group, ())
        return names[index - 1] if len(names) >= index else fallback

    def _feed_tickle(self, now: float) -> None:
        self._tickle_last = now
        if self._tickle_start is None:
            self._begin_action_fade(now)
            self._pose = None
            self._tickle_start = self._tickle_said = now
            self.gesture.emit("tickle")
        self._refresh(now)

    def _end_tickle(self, *, speak: bool = False, at: float | None = None) -> None:
        active = self._tickle_start is not None
        if active:
            self._finish_action_fade(self._clock() if at is None else at)
        self._tickle_start = None
        if active:
            self._tickle.clicks.clear()
            self._tickle.begin_rub(self._rub_last.x())
            if speak:
                self.gesture.emit("tickle_end")

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
        was_cheek = self._cheek_pulling
        was_cheek_move = self._cheek_mode and self._moved
        was_belly = self._belly_mode
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
        self._cheek_mode = self._cheek_pulling = self._belly_mode = False
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
        elif was_cheek:
            self._pose = self._gesture_sprite("cheek", 3, "stop")
            self._pose_until = now + CHEEK_RELEASE_SECONDS
            self.gesture.emit("cheek_release")
            self._refresh(now)
        elif was_belly:
            self.gesture.emit("belly")
            if not self._moved:
                if self._tickle.click(now) or self._tickle_start is not None:
                    self._feed_tickle(now)
            self._refresh(now)
        elif not was_pat and not was_cheek_move:
            self._animator.squash(now, "click")
            self._refresh(now)
            self.clicked.emit()
            if double:
                self.double_clicked.emit()

    def contextMenuEvent(self, e) -> None:
        self.menu_requested.emit(e.globalPos())

    # ---- 原地动作 ----
    def face(self, direction: int, *, automatic: bool = False) -> None:
        if self._dragging or self._falling or "turn" not in self._sequences:
            return
        self.stop_motion()
        self._end_tickle()
        self._begin_action_fade(self._clock())
        self._automatic_pose = automatic
        self._pose = self._gesture_sprite("turn", 2 if direction >= 0 else 8, "idle")
        self._pose_until = self._clock() + FACE_SECONDS
        self._refresh(self._clock())

    def turn(self, *, automatic: bool = False) -> None:
        if self._dragging or self._falling or "turn" not in self._sequences:
            return
        self.stop_motion()
        self._end_tickle()
        self._begin_action_fade(self._clock())
        self._automatic_pose = automatic
        self._turn_start = self._clock()
        self._refresh(self._clock())

    def set_calm(self, calm: bool) -> None:
        self._animator.calm = calm

    def set_activity(self, level: str) -> None:
        self._animator.activity_level = level

    @property
    def motion_active(self) -> bool:
        return (self._jump_start is not None or self._turn_start is not None
                or self._pose is not None or self._tickle_start is not None)

    @property
    def idle_motion_active(self) -> bool:
        return ((self._jump_start is not None and self._automatic_jump)
                or (self._automatic_pose and (self._turn_start is not None or self._pose is not None)))

    @property
    def is_pressed(self) -> bool:
        return self._press_global is not None

    def stop_motion(self) -> None:
        if (self._turn_start is not None or (self._pose is not None and not self._cheek_pulling)
                or (self._jump_start is not None and self._jump_framed)):
            self._finish_action_fade(self._clock())
        self._turn_start = None
        if not self._cheek_pulling:
            self._pose = None
        self._automatic_pose = False
        self._jump_start = None
        self._jump_offset = 0.0
        self._refresh(self._clock())

    def jump(self, *, automatic: bool = False) -> None:
        if self._dragging or self._falling:
            return
        self.stop_motion()
        self._end_tickle()
        self._automatic_jump = automatic
        self._jump_framed = "jump" in self._sequences
        if self._jump_framed:
            self._begin_action_fade(self._clock())
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
