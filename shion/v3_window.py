"""用 V3 纸偶显示的桌宠窗口（源码入口 --renderer v3，默认仍是 V2）。

窗口属性、状态机接口、V2 程序动作帧（压扁、倾斜、跳跃）、拖动/下落/夹边和
所有信号都沿用 PetWindow；这里只换“画什么”。手势在 S3/S4 接入前仍是 V2 规则。

帧节奏：互动和动作 60 FPS；头发轻摆时 30 FPS（睡着 15）；头发静止时待机/睡着 15 FPS、
工作 20 FPS，眨眼和轻摆开始前后临时 30 FPS。画面量化后没变就不重画。
"""
from __future__ import annotations

import math
import os
from collections import OrderedDict
from dataclasses import replace

import numpy as np
from PySide6.QtCore import QPoint, QPointF, Qt, Signal
from PySide6.QtGui import QBitmap, QGuiApplication, QImage, QPainter, QRegion, QTransform

from shion.animator import (BREATH_AMP, BREATH_PERIOD, BREATH_STATES, CALM_BREATH_AMP,
                            WORKING_BREATH_AMP, WORKING_BREATH_PERIOD)
from shion.behavior import BELLY_LIFT_DISTANCE, TICKLE_SPEECH_SECONDS, TICKLE_STOP_SECONDS
from shion.pet_window import (DRAG_THRESHOLD, MARGIN_BOTTOM, MARGIN_TOP, MARGIN_X, MASK_CACHE_MAX,
                              MASK_GROW, PetWindow)
from shion.v3_display import (STATE_EXPRESSIONS, V2_FOOT_GAP_RATIO, desired_side, draw_key,
                              expression_for, frame_interval, hair_moving, logical_scale)
from shion.v3_layers import SwayEnvelope, affine_ok, render_affine
from shion.v3_prewarm import BLINK_LEVELS, Prewarmer, quantize_eye

RENDERER_CACHE = 2  # 每侧最多两份（换屏 DPR 来回不重建）
AUTO_SIDE_ENV = "SHION_V3_AUTO_SIDE"  # 换边默认关闭；设为 1 才按屏幕位置换边
SIDE_STABLE_SECONDS = 0.5   # 位置/尺寸/屏幕连续这么久不变、也没在互动，才算“停稳”
SIDE_IDLE_RELEASE = 300.0   # 换走后旧侧闲置这么久就释放（rig、渲染器、预热缓存）
SIDE_SWAP_AT = 0.05         # 眨眼开始后这么久（闭眼最深在 0.06 秒）换边
SIDE_POP = 0.3              # 换边后新侧鼓脸颊“啵”：先按捏脸最大值的 30% 外拉，再由松手弹簧弹回
SIDE_PADDING = 48  # rig 像素：头发摆动、倾斜时不被裁掉
BELLY_HINT_DISTANCE = BELLY_LIFT_DISTANCE  # 肚子上没在挠、拖出这么远：提示“要拎脸颊”
LIFT_UP = 12.0     # 逻辑像素：脸颊上向上超过这么多，且竖向 > LIFT_RATIO × 横向，才算拎起
LIFT_RATIO = 1.2
MASK_INTERVAL = 0.1  # 秒：遮罩最多 10 次/秒
MASK_DRIFT_PX = 3.0  # 轮廓自上次遮罩漂过这么多像素就提前重建（遮罩外扩 MASK_GROW=4px）
PROGRAM_FAST_DEGREES_PER_SECOND = 8.0  # V2 程序动作：倾斜变化快于此用 60 FPS
PROGRAM_FAST_SCALE_PER_SECOND = 0.2    # 压扁/拉伸变化快于此用 60 FPS
SWAY_DEGREES = 2.0  # 轻摆满幅（原型默认值）
LEAD = 0.07  # 秒：眨眼、轻摆开始前提前提速

_RIGS: dict[str, object] = {}
# 测试可换成同步执行器；None 表示共用的后台线程
PREWARM_EXECUTOR = None


def load_rig(side: str):
    """加载一侧的 rig 并算好可见范围、脚底（约 0.3 秒；不碰全局缓存，后台线程可用）。"""
    from v3proto.render import Rig
    rig = Rig(cheek_side=side)
    alpha = np.asarray(rig.rest("neutral"))[..., 3]
    ys, xs = np.nonzero(alpha)
    hips = (rig.pivots["hip_l"][0] + rig.pivots["hip_r"][0]) / 2
    rig.v3_visible = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    rig.v3_foot = (float(hips), float(ys.max()) + 1)
    rig.v3_side = side
    return rig


def shared_rig(side: str = "left"):
    """进程内每侧只加载一次 rig（约 0.3 秒）。"""
    if side not in _RIGS:
        _RIGS[side] = load_rig(side)
    return _RIGS[side]


def _build_side(rig, side, scale):
    """后台：没有 rig 就加载，再建渲染器（约 0.3 + 0.3 秒）。"""
    from v3proto.render import Renderer
    if rig is None:
        rig = load_rig(side)
    return rig, Renderer(rig, scale)


def _premultiplied(image: QImage) -> np.ndarray:
    im = image.convertToFormat(QImage.Format.Format_RGBA8888_Premultiplied)
    a = np.frombuffer(im.constBits(), np.uint8).reshape(im.height(), im.bytesPerLine())
    return a[:, :im.width() * 4].reshape(im.height(), im.width(), 4).copy()


class V3PetWindow(PetWindow):
    renderer_name = "v3"
    # 敲头：True 表示 1.5 秒内第 3 下（抗议）。不算戳，不加好感。
    knocked = Signal(bool)
    # 在脸颊以外按住拖动超过点击容差（窗口不动）：控制器用它提示“捏着脸往上提”。
    drag_ignored = Signal()

    # ---- 尺寸与渲染器 ----
    def _v3_setup(self) -> None:
        if getattr(self, "_v3_ready", False):
            return
        from v3proto.animation import Animator, Settings
        self._v3_side = "left"
        self._v3_rig = shared_rig("left")
        self._v3_geometry = None  # 窗口几何只按第一次加载的 rig 算，换边不改窗口
        # 换边暂停（2026-11-10）：右鼓用的是 S5a 镜像脸部底板，桌面尺寸下刘海发丝断开、脸像歪了，
        # 等新画右鼓版底板再打开。开发时可设环境变量 SHION_V3_AUTO_SIDE=1 试用。
        self.auto_side = os.environ.get(AUTO_SIDE_ENV) == "1"
        self._v3_side_started = False
        self._v3_side_geom = None
        self._v3_side_since = 0.0
        self._v3_side_target: str | None = None
        self._v3_side_job = None
        self._v3_side_t0 = 0.0
        self._v3_side_blink: float | None = None
        self._v3_side_idle: dict[str, float] = {}
        self.v3_side_log: list[dict] = []  # 每次换边：准备耗时等（报告用）
        self._v3_renderers: OrderedDict[tuple, object] = OrderedDict()
        self._v3_prewarmers: dict[tuple, Prewarmer] = {}
        # 捏脸、敲头、摸头、挠痒（S3）和拎脸颊（S4）都用 V3 手势。
        self._v3_settings = Settings(expression="neutral", pinch=True, knock=True,
                                     pat=True, lift=True, tickle=True)
        self._v3_lifting = False
        self._v3_skip_refresh = False
        self._v3_lift_origin = QPoint()
        self._v3_lift_dizzy = False
        self._v3_idle_moved = False
        self._v3_ignored_sent = False
        self._v3_belly_tickled = False
        self._v3_press_point = None
        from v3proto.head_touch import HeadGesture
        from v3proto.tickle import BellyGesture
        self._v3_head_gesture = HeadGesture()
        self._v3_belly_gesture = BellyGesture()
        self._v3_gesture: str | None = None
        self._v3_cheek_started = False
        self._v3_cheek_local = None
        self._v3_belly_moved = False
        self._v3_tickle_start: float | None = None
        self._v3_tickle_last = 0.0
        self._v3_tickle_said = 0.0
        self._v3_animator = Animator(self._v3_settings)
        self._v3_clock: float | None = None
        self._v3_image: QImage | None = None
        self._v3_key = None
        self._v3_angles: dict | None = None
        self._v3_mask_at = -1e9
        self._v3_mask_frame = None  # 上次建遮罩时的 V2 帧 (sx, sy, angle, jump)
        self._v3_mask_force = True
        self._v3_mask_state = None
        self._v3_stats = {"refresh": 0, "rendered": 0, "masks": 0,
                          "affine": 0, "mesh": 0, "side_switches": 0}
        self._v3_sway = None
        self._v3_screen_hooked = False
        self._v3_ready = True

    def _load_sprites(self) -> None:
        self._v3_setup()
        screen = self.screen() if self.isVisible() else QGuiApplication.primaryScreen()
        dpr = self._pixel_ratio or (screen.devicePixelRatio() if screen else 1.0)
        self._apply_scale(dpr)

    def _apply_scale(self, dpr: float) -> None:
        if self._v3_geometry is None:
            self._v3_geometry = (self._v3_rig.v3_visible, self._v3_rig.v3_foot)
        (x0, y0, x1, y1), (foot_x, _) = self._v3_geometry
        self._v3_dpr = dpr
        self._v3_scale = logical_scale(self._height, y1 - y0)
        half = max(foot_x - x0, x1 - foot_x) + SIDE_PADDING
        self._sw = math.ceil(2 * half * self._v3_scale)
        self._sh = self._height
        self.normal_width = self._sw
        self._pixmaps.clear()
        self._sequences.clear()
        self._v3_renderer = self._renderer_for(self._height, dpr)
        self._v3_prewarmer = self._v3_prewarmers[self._v3_cache_key(self._v3_side, self._height, dpr)]
        self._v3_side_target = None  # 尺寸/DPR 变了：正在准备的另一侧作废，停稳后重来
        self._v3_side_job = None
        self._v3_side_blink = None
        self._v3_image = None
        self._v3_key = None
        self._v3_mask_force = True
        if hasattr(self, "_mask_cache"):
            self._mask_cache.clear()

    @staticmethod
    def _v3_cache_key(side: str, height: int, dpr: float) -> tuple:
        return (side, height, round(dpr, 4))

    def _renderer_for(self, height: int, dpr: float, side: str | None = None):
        side = side or self._v3_side
        key = self._v3_cache_key(side, height, dpr)
        if key in self._v3_renderers:
            self._v3_renderers.move_to_end(key)
            return self._v3_renderers[key]
        from v3proto.render import Renderer
        rig = shared_rig(side)
        renderer = Renderer(rig, self._v3_scale * dpr)
        self._v3_register(key, renderer)
        return renderer

    def _v3_register(self, key: tuple, renderer) -> None:
        """登记渲染器并排预热：当前表情（睁眼、闭眼档、捏脸素材）最先，其余随后。"""
        self._v3_renderers[key] = renderer
        prewarmer = Prewarmer(renderer, self._v3_settings, PREWARM_EXECUTOR)
        self._v3_prewarmers[key] = prewarmer
        current = self._v3_settings.expression
        prewarmer.request(current, (1.0, BLINK_LEVELS[0]))
        prewarmer.request_cheek(current)
        for expression in dict.fromkeys(STATE_EXPRESSIONS.values()):
            prewarmer.request(expression)
        for expression in dict.fromkeys(STATE_EXPRESSIONS.values()):
            prewarmer.request_cheek(expression)
        if renderer.head_surface.cheek.config:
            prewarmer.request_reactions(dict.fromkeys(STATE_EXPRESSIONS.values()), renderer.rig.faces)
        same = [k for k in self._v3_renderers if k[0] == key[0]]
        while len(same) > RENDERER_CACHE:  # 每侧最多两份（两种尺寸/DPR）；另一侧靠闲置释放
            old = same.pop(0)
            self._v3_renderers.pop(old)
            self._v3_prewarmers.pop(old).close()

    # ---- 换边（S5）----
    @property
    def cheek_side(self) -> str:
        return self._v3_side

    def _v3_desired_side(self) -> str:
        center = self.geometry().center()
        avail = self._screen_avail(center)
        return desired_side(center.x(), avail.left(), avail.width(), self._v3_side)

    def _v3_drop_side(self, side: str) -> None:
        """释放一侧：渲染器、预热器、预热缓存和 rig 本身。"""
        for key in [k for k in self._v3_renderers if k[0] == side]:
            self._v3_renderers.pop(key)
            self._v3_prewarmers.pop(key).close()
        self._v3_side_idle.pop(side, None)
        _RIGS.pop(side, None)

    def _v3_side_startup(self) -> None:
        """第一次显示：按恢复后的位置直接设定侧，不播过渡。"""
        self._v3_side_started = True
        if not self.auto_side:
            return
        want = self._v3_desired_side()
        if want == self._v3_side:
            return
        old = self._v3_side
        self._v3_side = want
        self._v3_rig = shared_rig(want)
        self._apply_scale(self._v3_dpr)
        self._v3_drop_side(old)

    def _v3_busy(self) -> bool:
        a = self._v3_animator
        return (a.interaction_active or self.is_pressed or self._dragging or self._falling
                or self._v3_lifting or self._jump_start is not None or self.motion_active
                or self._drag_playback is not None)

    def _v3_side_step(self, now: float) -> None:
        """每帧调一次：停稳 0.5 秒后判断该在哪一侧；要换就后台准备，就绪后眨眼换。"""
        for side, since in list(self._v3_side_idle.items()):
            if side not in (self._v3_side, self._v3_side_target) and now - since >= SIDE_IDLE_RELEASE:
                self._v3_drop_side(side)
        if not self.auto_side or not self._v3_side_started:
            return
        geom = (self.x(), self.y(), self.width(), self.height(), round(self._v3_dpr, 4))
        if self._v3_busy() or geom != self._v3_side_geom:
            self._v3_side_geom = geom
            self._v3_side_since = now
            self._v3_side_blink = None  # 眨眼途中开始互动/拖动：这次不换
            return
        if now - self._v3_side_since < SIDE_STABLE_SECONDS:
            return
        want = self._v3_desired_side()
        if want == self._v3_side:
            if self._v3_side_target is not None:  # 准备途中又不需要了
                self._v3_cancel_side()
            return
        if self._v3_side_target != want:
            self._v3_cancel_side()
            self._v3_start_side(want, now)
        key = self._v3_cache_key(want, self._height, self._v3_dpr)
        if key not in self._v3_prewarmers:
            job = self._v3_side_job
            if job is None or not job.done():
                return
            self._v3_side_job = None
            try:
                rig, renderer = job.result()
            except Exception:  # 准备失败：保持当前侧，下次停稳再试
                self._v3_side_target = None
                return
            _RIGS.setdefault(want, rig)
            self._v3_register(key, renderer)
        prewarmer = self._v3_prewarmers[key]
        prewarmer.collect()
        if not prewarmer.side_ready(self._v3_settings.expression):
            return
        a = self._v3_animator
        if self._v3_side_blink is None:
            a.blink_start = a.time          # 立刻眨一下
            self._v3_side_blink = a.time
            return
        if a.time - self._v3_side_blink >= SIDE_SWAP_AT:
            self._v3_swap_side(want, key, now)

    def _v3_start_side(self, side: str, now: float) -> None:
        self._v3_side_target = side
        self._v3_side_t0 = now
        self._v3_side_blink = None
        key = self._v3_cache_key(side, self._height, self._v3_dpr)
        if key in self._v3_prewarmers:
            self._v3_side_idle.pop(side, None)
            return
        executor = PREWARM_EXECUTOR or Prewarmer._shared_pool()
        self._v3_side_job = executor.submit(_build_side, _RIGS.get(side), side,
                                            self._v3_scale * self._v3_dpr)

    def _v3_cancel_side(self) -> None:
        side, self._v3_side_target = self._v3_side_target, None
        job, self._v3_side_job = self._v3_side_job, None
        self._v3_side_blink = None
        if job is not None:
            job.cancel()
        if side is not None and any(k[0] == side for k in self._v3_renderers):
            self._v3_side_idle.setdefault(side, self._clock())

    def _v3_swap_side(self, side: str, key: tuple, now: float) -> None:
        """眨眼闭眼那一帧换成另一侧，并让新侧鼓脸颊“啵”一下、头发甩一下。"""
        old = self._v3_side
        blink_elapsed = self._v3_animator.time - (self._v3_side_blink or self._v3_animator.time)
        self._v3_side = side
        self._v3_rig = self._v3_renderers[key].rig
        self._v3_renderers.move_to_end(key)
        self._v3_renderer = self._v3_renderers[key]
        self._v3_prewarmer = self._v3_prewarmers[key]
        self._v3_side_target = None
        self._v3_side_blink = None
        self._v3_side_idle.pop(side, None)
        self._v3_side_idle[old] = now
        self._v3_image = None
        self._v3_key = None
        self._v3_mask_force = True
        a = self._v3_animator
        if not a.dragging and not a.lift.active:
            a.delta = np.array([-SIDE_POP * a.settings.pinch_maximum, 0.0])  # 左侧语义：外拉为负
            a.velocity[:] = 0
        a.impulse(1 if side == "right" else -1)
        self._v3_stats["side_switches"] += 1
        self.v3_side_log.append({"from": old, "to": side, "prepare_s": round(now - self._v3_side_t0, 3),
                                 "blink_elapsed": round(blink_elapsed, 3)})

    def _v3_motion_point(self, local):
        """捏脸的点换到动画器的“左侧语义”：右侧时 x 反射，往外拉在两侧都是外拉。"""
        cheek = self._v3_renderer.head_surface.cheek
        return (cheek.motion_x(local[0]), local[1])

    def set_device_pixel_ratio(self, dpr: float) -> None:
        """换到 DPR 不同的屏幕：重建（或取缓存的）渲染器，脚底不动。"""
        if self._pixel_ratio is not None or abs(dpr - self._v3_dpr) < 1e-6:
            return
        self._apply_scale(dpr)
        self._refresh(self._clock())

    def _on_screen_changed(self, screen) -> None:
        if screen is not None:
            self.set_device_pixel_ratio(screen.devicePixelRatio())

    def showEvent(self, e) -> None:
        if not self._v3_side_started:
            self._v3_side_startup()
        if not self._v3_screen_hooked and self.windowHandle() is not None:
            self.windowHandle().screenChanged.connect(self._on_screen_changed)
            self._v3_screen_hooked = True
            self._on_screen_changed(self.windowHandle().screen())
        super().showEvent(e)
        if self._timer is not None and not self._timer.isActive() and getattr(self, "_v3_resume", False):
            self._timer.start()

    def hideEvent(self, e) -> None:
        self._v3_resume = self._timer.isActive()
        self._timer.stop()
        super().hideEvent(e)

    @property
    def v3_texture_scale(self) -> float:
        """设备像素 / rig 像素。"""
        return self._v3_scale * self._v3_dpr

    @property
    def v3_expression(self) -> str:
        return self._v3_settings.expression

    @property
    def v3_stats(self) -> dict:
        return dict(self._v3_stats)

    def head_anchor(self) -> QPoint:
        """头顶中心（全局坐标）：按 rig 实际头顶算。"""
        rig = self._v3_rig
        foot_y = rig.v3_foot[1]
        top = rig.v3_visible[1]
        gap = self._height * V2_FOOT_GAP_RATIO
        y = self.height() - MARGIN_BOTTOM - gap - (foot_y - top) * self._v3_scale
        return self.mapToGlobal(QPoint(self.width() // 2, round(y + self._sh * 0.04)))

    # ---- 每帧 ----
    def closeEvent(self, e) -> None:
        for prewarmer in getattr(self, "_v3_prewarmers", {}).values():
            prewarmer.close()
        super().closeEvent(e)

    def _without_v2_breath(self, f):
        """V3 自己呼吸；去掉 V2 动画器给整张图加的呼吸缩放，保留其余程序动作。"""
        state = self._animator.state
        a = self._animator
        if state in ("bed", "desk") or not (state in BREATH_STATES or state == "working" or a.calm):
            return f
        amp = BREATH_AMP if state in BREATH_STATES else CALM_BREATH_AMP
        period = BREATH_PERIOD
        if state == "working":
            amp, period = WORKING_BREATH_AMP, WORKING_BREATH_PERIOD
        if a._from_pose is not None:  # 切换过渡里 V2 自己在插值，不去掉
            return f
        t = self._clock() - a._t0
        breath = 1.0 + (amp / 2) * (1.0 - math.cos(2 * math.pi * t / period))
        from dataclasses import replace
        return replace(f, sy=f.sy / breath)

    def _program_active(self, f, dt: float) -> bool:
        """V2 程序动作是否在快速变化。待机轻摇（约 1°、几秒一周期）不算。"""
        if (self.motion_active or self._dragging or self._falling or self.is_pressed
                or self._drag_playback is not None or self._action_fade is not None
                or self._jump_offset != 0):
            return True
        last = getattr(self, "_v3_last_frame", None)
        self._v3_last_frame = f
        if last is None or dt <= 0:
            return False
        return (abs(f.angle - last.angle) > PROGRAM_FAST_DEGREES_PER_SECOND * dt
                or abs(f.sy - last.sy) > PROGRAM_FAST_SCALE_PER_SECOND * dt
                or abs(f.sx - last.sx) > PROGRAM_FAST_SCALE_PER_SECOND * dt)

    def _refresh(self, now: float) -> None:
        if self._v3_skip_refresh:
            return
        stats = self._v3_stats
        stats["refresh"] += 1
        self._animator.idle_enabled = not (self.motion_active or self._dragging or self._falling
                                          or self.is_pressed or self._drag_playback is not None)
        f = self._animator.frame(now)
        f = self._action_frame(now, f)
        f = self._blend_action(now, f)
        f = self._without_v2_breath(f)
        shown = max(f.layers, key=lambda item: item[1])[0] if f.layers else f.sprite
        expression = expression_for(shown, self.sprite_name)
        if expression != self._v3_settings.expression or self.sprite_name != self._v3_mask_state:
            self._v3_mask_force = True
            self._v3_mask_state = self.sprite_name
        self._v3_settings.expression = expression
        dt = 0.0 if self._v3_clock is None else max(0.0, now - self._v3_clock)
        self._v3_clock = now
        animator = self._v3_animator
        if self._v3_sway is None:
            self._v3_sway = SwayEnvelope(now)
        if animator.interaction_active:
            self._v3_sway.force(now)
        self._v3_settings.sway_degrees = SWAY_DEGREES * self._v3_sway.value(now)
        pose = animator.advance(dt)
        if animator.lift.active:
            pose.root_offset = (0.0, 0.0)  # 窗口自己在动；root_roll / 身体 / 手臂照常
        self._v3_side_step(now)
        if any(animator.delta) and not any(pose.pinch_delta):
            pose = replace(pose, pinch_delta=tuple(animator.delta))  # 换边“啵”的第一帧就带上拉伸
        prewarmer = self._v3_prewarmer
        prewarmer.collect()
        if animator.interaction_active or self.is_pressed or self._dragging:
            prewarmer.cancel_blinks()
        else:
            prewarmer.request_blinks(expression)
        eye = quantize_eye(pose.eye_scale)
        if pose.reaction_face is None:
            eye = prewarmer.choose(expression, eye)
        elif eye < 1.0 and (pose.reaction_face, round(eye, 5), False) not in \
                self._v3_renderer.head_surface.reaction_face.cache:
            eye = 1.0  # 反应脸的眨眼补丁没算过：这次不眨（现算一张约 50ms，会卡一下）
        if eye != pose.eye_scale:
            pose = replace(pose, eye_scale=eye)
        moving_hair = hair_moving(self._v3_angles, pose.angles, dt)
        self._v3_angles = dict(pose.angles)
        program = self._program_active(f, dt)
        fast = (program or self._v3_animator.interaction_active
                or moving_hair or pose.star_effects or self._v3_side_blink is not None
                or any(pose.pinch_delta))
        still = affine_ok(pose)
        soon = (pose.eye_scale < 1 or 0 <= animator.blink_start - animator.time <= LEAD
                or self._v3_sway.until_start(now) <= LEAD)
        interval = frame_interval(bool(fast), self.sprite_name, still, soon)
        if self._timer.interval() != interval:
            self._timer.setInterval(interval)
        frame_key = (round(f.sx / 0.002), round(f.sy / 0.002), round(f.angle / 0.1),
                     round(self._jump_offset * 4))
        key = draw_key(expression, pose, self.v3_texture_scale, frame_key)
        self._sync_sleep_z(now, f)
        self._frame = f
        if key is not None and key == self._v3_key and self._v3_image is not None:
            return
        self._v3_key = key
        if still:
            image = render_affine(self._v3_renderer, self._v3_settings, pose)
            stats["affine"] += 1
        else:
            image = self._v3_renderer.render(self._v3_settings, pose)
            stats["mesh"] += 1
        image.setDevicePixelRatio(self._v3_dpr)
        self._v3_image = image
        stats["rendered"] += 1
        # 遮罩最多 10 次/秒；但 V2 帧（倾斜/压扁/跳）快速变化时轮廓每帧都在动，遮罩滞后会
        # 把落地回弹时伸出遮罩的头发尖裁掉（看起来闪一下），这时才每帧重建。
        # 判据是“轮廓相对上次遮罩漂了多少像素”，不是“有没有按着鼠标”：setMask 是原生调用，
        # 约 4ms/次，按着摸头时每帧重建会让每帧多花 5ms。
        if (self._v3_mask_force or now - self._v3_mask_at >= MASK_INTERVAL
                or self._v3_mask_stale(f) or self._v3_animator.lift.active):
            self._update_mask(now)
        self.update()
        if self._fps_overlay is not None:
            self._fps_overlay.follow()
        if self._pause_badge is not None:
            self._pause_badge.follow()

    # ---- 手势（S3）----
    def _v3_transform(self, f) -> QTransform:
        """与 _draw_sprite 完全相同的 窗口 ← 图像 变换。"""
        t = QTransform()
        t.translate(self.width() / 2, self.height() - MARGIN_BOTTOM - self._jump_offset)
        t.rotate(f.angle)
        t.scale(f.sx, f.sy)
        return t

    def _to_rig(self, pos):
        """窗口坐标 → rig 坐标（反推 _draw_sprite 的变换，含 V2 压扁/倾斜/跳跃）。"""
        f = getattr(self, "_frame", None)
        if f is None or self._v3_image is None:
            return None
        inverse, ok = self._v3_transform(f).inverted()
        if not ok:
            return None
        p = inverse.map(QPointF(pos))
        foot_x, foot_y = self._v3_rig.v3_foot
        s = self._v3_scale
        gap = self._height * V2_FOOT_GAP_RATIO
        return np.array([p.x() / s + foot_x, (p.y() + gap) / s + foot_y])

    def _v3_hit(self, pos):
        point = self._to_rig(pos)
        if point is None:
            return None, None, None
        hit, local = self._v3_renderer.hit_test(point, self._v3_settings, self._v3_animator.pose,
                                                crown=True, belly=True)
        return hit, local, point

    def _hit_zone(self, pos: QPoint) -> str:
        """V2 的矩形分区不用：窗口内一律当身体，手势由 V3 命中判断。"""
        return "outside" if super()._hit_zone(pos) == "outside" else "body"

    def _update_hover_cursor(self, pos: QPoint) -> None:
        hit, _, _ = self._v3_hit(QPointF(pos))
        if hit in ("cheek", "crown", "belly"):
            self.setCursor(Qt.OpenHandCursor)
        else:
            self.unsetCursor()

    def mousePressEvent(self, e) -> None:
        super().mousePressEvent(e)
        self._v3_gesture = None
        self._v3_idle_moved = False
        self._v3_ignored_sent = False
        self._v3_belly_tickled = False
        if e.button() != Qt.LeftButton or self._press_global is None:
            return
        hit, local, point = self._v3_hit(e.position())
        if hit == "cheek":  # 接住下落中的宠物时也可以捏、可以拎
            self._v3_gesture = "cheek"
            self._v3_cheek_started = False
            self._v3_cheek_local = local
            self._v3_press_point = point
        elif self._caught_fall:
            self._v3_gesture = "idle"
        elif hit == "crown":
            self._v3_gesture = "crown"
            self._v3_head_gesture.press((e.position().x(), e.position().y()))
            self.setCursor(Qt.ClosedHandCursor)
        elif hit == "belly":
            self._v3_gesture = "belly"
            self._v3_belly_gesture.press((e.position().x(), e.position().y()))
            self._v3_belly_moved = False
            self.gesture.emit("belly")
            self.setCursor(Qt.ClosedHandCursor)
        else:
            # 脸、头发、身体、空白：只能点击（戳）。窗口只能靠拎脸颊移动，按住拖不动。
            if hit in ("face", "head"):
                self._v3_animator.impulse(1 if point[0] >= self._v3_rig.pivots["neck"][0] else -1)
            self._v3_gesture = "idle"

    def stop_motion(self) -> None:
        # 摸头每 40px 控制器会调一次；父类末尾会立刻同步渲染一帧（V3 约 10ms），手势进行中
        # 交给定时器下一帧画。
        self._v3_skip_refresh = self._v3_gesture is not None
        try:
            super().stop_motion()
        finally:
            self._v3_skip_refresh = False

    def _v3_notify_ignored(self) -> None:
        if not self._v3_ignored_sent:
            self._v3_ignored_sent = True
            self.drag_ignored.emit()

    def mouseMoveEvent(self, e) -> None:
        kind = self._v3_gesture
        if kind is None or self._press_global is None or not (e.buttons() & Qt.LeftButton):
            super().mouseMoveEvent(e)
            return
        a = self._v3_animator
        now = self._clock()
        if self._v3_lifting:
            super().mouseMoveEvent(e)  # 真实窗口跟着鼠标走（父类的拖动分支）
            self._v3_lift_follow()
            return
        gp = e.globalPosition().toPoint()
        self._release_velocity.feed(self._clock(), gp.x(), gp.y())
        d = gp - self._press_global
        distance = math.hypot(d.x(), d.y())
        pos = (e.position().x(), e.position().y())
        if kind == "idle":
            if distance > DRAG_THRESHOLD:
                self._v3_idle_moved = True
                self._v3_notify_ignored()
            return
        if kind == "cheek":
            up = -d.y()
            if up > LIFT_UP and up > LIFT_RATIO * abs(d.x()):
                self._v3_begin_lift(e)
                return
            if not self._v3_cheek_started and abs(d.x()) <= DRAG_THRESHOLD:
                return
            if not self._v3_cheek_started:
                self._v3_cheek_started = True
                a.press(self._v3_motion_point(self._v3_cheek_local))
                self.setCursor(Qt.ClosedHandCursor)
                self.gesture.emit("cheek_pull")
            point = self._to_rig(e.position())
            if point is not None:
                local = self._v3_renderer.head_surface.source_point(
                    self._v3_renderer.rig_point(point, a.pose), a.pose, allow_outside=True)
                if local is not None:
                    a.drag(self._v3_motion_point(local))
        elif kind == "crown":
            delta = self._v3_head_gesture.move(pos, True)
            self._pat_step(gp)
            if delta:
                a.stroke_head(delta)
        else:
            if distance > DRAG_THRESHOLD:
                self._v3_belly_moved = True
            action = self._v3_belly_gesture.move(pos, now)
            if action == "pause":
                a.release_tickle()  # 停手：手势保持，再揉可以接着挠
            elif action == "tickle":
                self._v3_belly_tickled = True
                a.tickle_belly()
                self._v3_tickle_touch(now)
            if not self._v3_belly_tickled and distance > BELLY_HINT_DISTANCE:
                self._v3_notify_ignored()
        # 这里不 _refresh：鼠标一秒可以发几百个移动事件，每个都渲染一帧会把界面线程占满
        #（125Hz 摸头每帧 13ms，250Hz 27ms）。动画状态已更新，定时器下一帧（60 FPS）画出来。

    # ---- 拎脸颊（S4）----
    @property
    def lifting(self) -> bool:
        return self._v3_lifting

    def _v3_begin_lift(self, e) -> None:
        """脸颊上向上拖：V3 拎起反应 + 真实窗口跟着走（父类拖动：移动、下落、夹边、信号）。"""
        a = self._v3_animator
        a.advance(0)
        point = self._v3_press_point
        pivot = self._v3_renderer.rig_point(point, a.pose) if point is not None else point
        a.begin_lift(tuple(pivot) if pivot is not None else (543.0, 586.0), cheek=True)
        self._v3_cheek_started = False  # 捏脸转拎起：松手不再说 cheek_release
        self._v3_lifting = True
        self._v3_lift_origin = self.pos()
        super().mouseMoveEvent(e)  # drag_started 在这里发，此时 lifting 已为 True
        self._animator.set_drag(False)  # V2 的拖动倾斜让给 V3 的 root_roll，不叠加
        self._v3_lift_follow()
        self._refresh(self._clock())

    def _v3_lift_follow(self) -> None:
        disp = self.pos() - self._v3_lift_origin
        s = self._v3_scale
        # 画面不再平移（窗口自己在动），位移只用来算速度、倾斜和晃晕。
        self._v3_animator.move_lift((disp.x() / s, disp.y() / s), float(disp.x()), clamp=False)

    def consume_shaken(self) -> bool:
        """晃晕以 V3 拎起的判断为准（来回 ≥24px 三次/2 秒），和画面上的晕脸一致。"""
        super().consume_shaken()
        shaken, self._v3_lift_dizzy = self._v3_lift_dizzy, False
        return shaken

    def mouseReleaseEvent(self, e) -> None:
        kind = self._v3_gesture
        if kind is None or e.button() != Qt.LeftButton or self._press_global is None:
            super().mouseReleaseEvent(e)
            self._v3_gesture = None
            return
        self._v3_gesture = None
        a = self._v3_animator
        now = self._clock()
        if self._v3_lifting:
            self._v3_lift_dizzy = self._v3_lift_dizzy or a.lift.dizzy
            a.release_lift()
            self._v3_lifting = False
            super().mouseReleaseEvent(e)  # 慢放：原地停留并夹边；快甩/放到任务栏：下落
            self._refresh(now)
            return
        consumed = False
        if kind == "cheek":
            if self._v3_cheek_started:
                a.release()
                self.gesture.emit("cheek_release")
                consumed = True
        elif kind == "crown":
            pos = (e.position().x(), e.position().y())
            delta = self._v3_head_gesture.move(pos, True)
            if delta:
                a.stroke_head(delta)
            patting = self._v3_head_gesture.patting
            if self._v3_head_gesture.release():
                point = self._to_rig(e.position())
                neck_x = self._v3_rig.pivots["neck"][0]
                direction = 1 if point is None or point[0] >= neck_x else -1
                a.knock_head(direction, point=tuple(point) if point is not None else (500., 150.))
                self.knocked.emit(a.head_touch.stage == "protest")
            elif patting:
                a.release_head()
            consumed = True
        elif kind == "idle":
            consumed = self._v3_idle_moved
        else:
            a.release_tickle()
            consumed = self._v3_belly_moved
        if consumed:  # 让父类按“已被手势吃掉”复位按下状态：不发 clicked、不压扁
            self._pat_mode = True
            self._moved = True
        super().mouseReleaseEvent(e)
        self._refresh(now)

    def focusOutEvent(self, e) -> None:
        self._v3_abort()
        super().focusOutEvent(e)

    def _v3_abort(self) -> None:
        """放弃当前手势（失焦）：动画归位，不发 release 台词。"""
        kind, self._v3_gesture = self._v3_gesture, None
        a = self._v3_animator
        if self._v3_lifting:
            self._v3_lift_dizzy = self._v3_lift_dizzy or a.lift.dizzy
            a.release_lift()
            self._v3_lifting = False
        elif kind == "cheek" and self._v3_cheek_started:
            a.release()
        elif kind == "crown":
            self._v3_head_gesture.clear()
            a.release_head()
        elif kind == "belly":
            self._v3_belly_gesture.clear()
            a.release_tickle()
        self._v3_cheek_started = False

    def _v3_tickle_touch(self, now: float) -> None:
        self._v3_tickle_last = now
        if self._v3_tickle_start is None:
            self._v3_tickle_start = self._v3_tickle_said = now
            self.gesture.emit("tickle")

    def _v3_end_tickle(self, *, speak: bool) -> None:
        if self._v3_tickle_start is None:
            return
        self._v3_tickle_start = None
        self._v3_animator.release_tickle()
        if speak:
            self.gesture.emit("tickle_end")

    @property
    def motion_active(self) -> bool:
        return super().motion_active or self._v3_tickle_start is not None

    def advance_to(self, now: float) -> None:
        if self._v3_tickle_start is not None:
            if now - self._v3_tickle_last + 1e-9 >= TICKLE_STOP_SECONDS:
                self._v3_end_tickle(speak=True)
            elif now - self._v3_tickle_said >= TICKLE_SPEECH_SECONDS:
                self._v3_tickle_said = now
                self.gesture.emit("tickle")
        super().advance_to(now)

    # ---- 遮罩 ----
    def _v3_mask_stale(self, f) -> bool:
        """V2 帧（压扁/倾斜/跳）自上次建遮罩以来，轮廓估计漂了多少像素；超过 MASK_DRIFT_PX 就重建。"""
        ref = self._v3_mask_frame
        if ref is None:
            return True
        sx, sy, angle, jump = ref
        h = self.height()
        drift = (h * (abs(f.sx - sx) + abs(f.sy - sy))
                 + 0.5 * h * math.radians(abs(f.angle - angle)) + abs(self._jump_offset - jump))
        return drift > MASK_DRIFT_PX

    def _update_mask(self, now: float) -> None:
        self._v3_mask_at = now
        f = getattr(self, "_frame", None)
        if f is not None:
            self._v3_mask_frame = (f.sx, f.sy, f.angle, self._jump_offset)
        self._v3_mask_force = False
        img = QImage(self.size(), QImage.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        p.setRenderHints(QPainter.SmoothPixmapTransform | QPainter.Antialiasing)
        self._draw_sprite(p, self._frame)
        p.end()
        base = QRegion(QBitmap.fromImage(img.createMaskFromColor(0, Qt.MaskInColor)))
        region = QRegion(base)
        g = MASK_GROW
        for dx, dy in ((g, 0), (-g, 0), (0, g), (0, -g), (g, g), (-g, g), (g, -g), (-g, -g),
                       (g // 2, 0), (-g // 2, 0), (0, g // 2), (0, -g // 2)):
            region |= base.translated(dx, dy)
        region &= QRegion(self.rect())
        self._v3_stats["masks"] += 1
        self._v3_region = region
        self.setMask(region)

    def _mask_for(self, f) -> QRegion:
        """父类改尺寸等路径会调用；V3 统一用当前帧的遮罩。"""
        if getattr(self, "_v3_region", None) is None or self._v3_mask_force:
            if self._v3_image is not None:
                self._update_mask(self._clock())
        return getattr(self, "_v3_region", QRegion(self.rect()))

    def _draw_sprite(self, p: QPainter, f) -> None:
        if self._v3_image is None:
            return
        rig = self._v3_rig
        foot_x, foot_y = rig.v3_foot
        s = self._v3_scale
        p.save()
        p.translate(self.width() / 2, self.height() - MARGIN_BOTTOM - self._jump_offset)
        p.rotate(f.angle)
        p.scale(f.sx, f.sy)
        gap = self._height * V2_FOOT_GAP_RATIO
        p.drawImage(QPointF(-foot_x * s, -gap - foot_y * s), self._v3_image)
        p.restore()


__all__ = ["V3PetWindow", "shared_rig", "MARGIN_X", "MARGIN_TOP", "MASK_CACHE_MAX"]
