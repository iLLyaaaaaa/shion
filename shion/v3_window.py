"""用 V3 纸偶显示的桌宠窗口（源码入口 --renderer v3，默认仍是 V2）。

窗口属性、状态机接口、V2 程序动作帧（压扁、倾斜、跳跃）、拖动/下落/夹边和
所有信号都沿用 PetWindow；这里只换“画什么”。手势在 S3/S4 接入前仍是 V2 规则。

帧节奏：互动和动作 60 FPS；头发轻摆时 30 FPS（睡着 15）；头发静止时待机/睡着 15 FPS、
工作 20 FPS，眨眼和轻摆开始前后临时 30 FPS。画面量化后没变就不重画。
"""
from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import replace

import numpy as np
from PySide6.QtCore import QPoint, QPointF, Qt, Signal
from PySide6.QtGui import QBitmap, QGuiApplication, QImage, QPainter, QRegion, QTransform

from shion.animator import (BREATH_AMP, BREATH_PERIOD, BREATH_STATES, CALM_BREATH_AMP,
                            WORKING_BREATH_AMP, WORKING_BREATH_PERIOD)
from shion.behavior import (BELLY_LIFT_DISTANCE, CHEEK_LIFT_DISTANCE, TICKLE_SPEECH_SECONDS,
                            TICKLE_STOP_SECONDS)
from shion.pet_window import (DRAG_THRESHOLD, MARGIN_BOTTOM, MARGIN_TOP, MARGIN_X, MASK_CACHE_MAX,
                              MASK_GROW, PetWindow)
from shion.v3_display import (STATE_EXPRESSIONS, V2_FOOT_GAP_RATIO, draw_key,
                              expression_for, frame_interval, hair_moving, logical_scale)
from shion.v3_layers import SwayEnvelope, affine_ok, render_affine
from shion.v3_prewarm import Prewarmer, quantize_eye

RENDERER_CACHE = 2
SIDE_PADDING = 48  # rig 像素：头发摆动、倾斜时不被裁掉
BELLY_DRAG_DISTANCE = BELLY_LIFT_DISTANCE  # 没在挠时拖出这么远，转整窗拖动
MASK_INTERVAL = 0.1  # 秒：遮罩最多 10 次/秒
PROGRAM_FAST_DEGREES_PER_SECOND = 8.0  # V2 程序动作：倾斜变化快于此用 60 FPS
PROGRAM_FAST_SCALE_PER_SECOND = 0.2    # 压扁/拉伸变化快于此用 60 FPS
SWAY_DEGREES = 2.0  # 轻摆满幅（原型默认值）
LEAD = 0.07  # 秒：眨眼、轻摆开始前提前提速

_RIGS: dict[str, object] = {}
# 测试可换成同步执行器；None 表示共用的后台线程
PREWARM_EXECUTOR = None


def shared_rig(side: str = "left"):
    """进程内每侧只加载一次 rig（约 0.3 秒）。"""
    if side not in _RIGS:
        from v3proto.render import Rig
        rig = Rig(cheek_side=side)
        alpha = np.asarray(rig.rest("neutral"))[..., 3]
        ys, xs = np.nonzero(alpha)
        hips = (rig.pivots["hip_l"][0] + rig.pivots["hip_r"][0]) / 2
        rig.v3_visible = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
        rig.v3_foot = (float(hips), float(ys.max()) + 1)
        _RIGS[side] = rig
    return _RIGS[side]


def _premultiplied(image: QImage) -> np.ndarray:
    im = image.convertToFormat(QImage.Format.Format_RGBA8888_Premultiplied)
    a = np.frombuffer(im.constBits(), np.uint8).reshape(im.height(), im.bytesPerLine())
    return a[:, :im.width() * 4].reshape(im.height(), im.width(), 4).copy()


class V3PetWindow(PetWindow):
    renderer_name = "v3"
    # 敲头：True 表示 1.5 秒内第 3 下（抗议）。不算戳，不加好感。
    knocked = Signal(bool)

    # ---- 尺寸与渲染器 ----
    def _v3_setup(self) -> None:
        if getattr(self, "_v3_ready", False):
            return
        from v3proto.animation import Animator, Settings
        self._v3_rig = shared_rig("left")
        self._v3_renderers: OrderedDict[tuple, object] = OrderedDict()
        self._v3_prewarmers: dict[tuple, Prewarmer] = {}
        # 捏脸、敲头、摸头、挠痒用 V3 手势（S3）；拎起 S4 接入，先关着。
        self._v3_settings = Settings(expression="neutral", pinch=True, knock=True,
                                     pat=True, lift=False, tickle=True)
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
        self._v3_mask_key = None  # 上次建遮罩时的 V2 帧键；变了就立刻重建
        self._v3_mask_force = True
        self._v3_mask_state = None
        self._v3_stats = {"refresh": 0, "rendered": 0, "masks": 0,
                          "affine": 0, "mesh": 0}
        self._v3_sway = None
        self._v3_screen_hooked = False
        self._v3_ready = True

    def _load_sprites(self) -> None:
        self._v3_setup()
        screen = self.screen() if self.isVisible() else QGuiApplication.primaryScreen()
        dpr = self._pixel_ratio or (screen.devicePixelRatio() if screen else 1.0)
        self._apply_scale(dpr)

    def _apply_scale(self, dpr: float) -> None:
        rig = self._v3_rig
        x0, y0, x1, y1 = rig.v3_visible
        foot_x, _ = rig.v3_foot
        self._v3_dpr = dpr
        self._v3_scale = logical_scale(self._height, y1 - y0)
        half = max(foot_x - x0, x1 - foot_x) + SIDE_PADDING
        self._sw = math.ceil(2 * half * self._v3_scale)
        self._sh = self._height
        self.normal_width = self._sw
        self._pixmaps.clear()
        self._sequences.clear()
        self._v3_renderer = self._renderer_for(self._height, dpr)
        self._v3_prewarmer = self._v3_prewarmers[(self._height, round(dpr, 4))]
        self._v3_image = None
        self._v3_key = None
        self._v3_mask_force = True
        if hasattr(self, "_mask_cache"):
            self._mask_cache.clear()

    def _renderer_for(self, height: int, dpr: float):
        key = (height, round(dpr, 4))
        if key in self._v3_renderers:
            self._v3_renderers.move_to_end(key)
            return self._v3_renderers[key]
        from v3proto.render import Renderer
        renderer = Renderer(self._v3_rig, self._v3_scale * dpr)
        self._v3_renderers[key] = renderer
        prewarmer = Prewarmer(renderer, self._v3_settings, PREWARM_EXECUTOR)
        self._v3_prewarmers[key] = prewarmer
        # 当前表情先排，其余正式状态会用到的表情的睁眼帧随后
        current = self._v3_settings.expression
        prewarmer.request(current)
        for expression in dict.fromkeys(STATE_EXPRESSIONS.values()):
            prewarmer.request(expression)
        prewarmer.request_cheek(current)
        for expression in dict.fromkeys(STATE_EXPRESSIONS.values()):
            prewarmer.request_cheek(expression)
        if renderer.head_surface.cheek.config:
            prewarmer.request_reactions(dict.fromkeys(STATE_EXPRESSIONS.values()), self._v3_rig.faces)
        while len(self._v3_renderers) > RENDERER_CACHE:
            old, _ = self._v3_renderers.popitem(last=False)
            self._v3_prewarmers.pop(old).close()
        return renderer

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
        prewarmer = self._v3_prewarmer
        prewarmer.collect()
        prewarmer.request_blinks(expression)
        eye = quantize_eye(pose.eye_scale)
        if pose.reaction_face is None:
            eye = prewarmer.choose(expression, eye)
        if eye != pose.eye_scale:
            pose = replace(pose, eye_scale=eye)
        moving_hair = hair_moving(self._v3_angles, pose.angles, dt)
        self._v3_angles = dict(pose.angles)
        program = self._program_active(f, dt)
        fast = (program or self._v3_animator.interaction_active
                or moving_hair or pose.star_effects)
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
        # 遮罩最多 10 次/秒；但 V2 帧（倾斜/压扁/跳）在变时轮廓每帧都在动，遮罩滞后会
        # 把落地回弹时伸出遮罩的头发尖裁掉（看起来闪一下），这时每帧重建。
        if (self._v3_mask_force or now - self._v3_mask_at >= MASK_INTERVAL
                or (program and frame_key != self._v3_mask_key)):
            self._update_mask(now)
            self._v3_mask_key = frame_key
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
        if e.button() != Qt.LeftButton or self._press_global is None or self._caught_fall:
            return
        hit, local, point = self._v3_hit(e.position())
        if hit == "cheek":
            self._v3_gesture = "cheek"
            self._v3_cheek_started = False
            self._v3_cheek_local = local
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
        elif hit in ("face", "head"):
            self._v3_animator.impulse(1 if point[0] >= self._v3_rig.pivots["neck"][0] else -1)

    def mouseMoveEvent(self, e) -> None:
        kind = self._v3_gesture
        if kind is None or self._press_global is None or not (e.buttons() & Qt.LeftButton):
            super().mouseMoveEvent(e)
            return
        gp = e.globalPosition().toPoint()
        self._release_velocity.feed(self._clock(), gp.x(), gp.y())
        d = gp - self._press_global
        distance = math.hypot(d.x(), d.y())
        pos = (e.position().x(), e.position().y())
        a = self._v3_animator
        now = self._clock()
        if kind == "cheek":
            if distance > CHEEK_LIFT_DISTANCE:  # S3 过渡：拉过头变成整窗拖动，S4 改为拎起
                self._v3_abort()
                super().mouseMoveEvent(e)
                return
            if not self._v3_cheek_started and abs(d.x()) <= DRAG_THRESHOLD:
                return
            if not self._v3_cheek_started:
                self._v3_cheek_started = True
                a.press(self._v3_cheek_local)
                self.setCursor(Qt.ClosedHandCursor)
                self.gesture.emit("cheek_pull")
            point = self._to_rig(e.position())
            if point is not None:
                local = self._v3_renderer.head_surface.source_point(
                    self._v3_renderer.rig_point(point, a.pose), a.pose, allow_outside=True)
                if local is not None:
                    a.drag(local)
        elif kind == "crown":
            delta = self._v3_head_gesture.move(pos, True)
            self._pat_step(gp)
            if delta:
                a.stroke_head(delta)
        else:
            if distance > DRAG_THRESHOLD:
                self._v3_belly_moved = True
            if self._v3_tickle_start is None and distance > BELLY_DRAG_DISTANCE:
                # 没在挠：转整窗拖动（S3 过渡，S4 起只能拎脸颊移动）
                self._v3_abort()
                super().mouseMoveEvent(e)
                return
            action = self._v3_belly_gesture.move(pos, now)
            if action == "pause":
                self._v3_abort()
                super().mouseMoveEvent(e)
                return
            if action == "tickle":
                a.tickle_belly()
                self._v3_tickle_touch(now)
        self._refresh(now)

    def mouseReleaseEvent(self, e) -> None:
        kind = self._v3_gesture
        if kind is None or e.button() != Qt.LeftButton or self._press_global is None:
            super().mouseReleaseEvent(e)
            self._v3_gesture = None
            return
        self._v3_gesture = None
        a = self._v3_animator
        now = self._clock()
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
        """放弃当前手势（拉过头、失焦）：动画归位，不发 release 台词。"""
        kind, self._v3_gesture = self._v3_gesture, None
        a = self._v3_animator
        if kind == "cheek" and self._v3_cheek_started:
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
    def _update_mask(self, now: float) -> None:
        self._v3_mask_at = now
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
