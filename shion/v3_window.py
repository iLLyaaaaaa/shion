"""用 V3 纸偶显示的桌宠窗口（唯一外观；v3.0.0 起没有渲染器开关）。

窗口属性、状态机接口、V2 程序动作帧（压扁、倾斜、跳跃）、拖动/下落/夹边和
所有信号都沿用 PetWindow；这里只换“画什么”。手势在 S3/S4 接入前仍是 V2 规则。

帧节奏：互动和动作 60 FPS；头发轻摆时 30 FPS（睡着 15）；头发静止时待机/睡着 15 FPS、
工作 20 FPS，眨眼和轻摆开始前后临时 30 FPS。画面量化后没变就不重画。
"""
from __future__ import annotations

import gc
import math
import os
import time
from collections import OrderedDict
from dataclasses import replace

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBitmap, QGuiApplication, QImage, QPainter, QRegion, QTransform

from shion.animator import (BREATH_AMP, BREATH_PERIOD, BREATH_STATES, CALM_BREATH_AMP,
                            WORKING_BREATH_AMP, WORKING_BREATH_PERIOD)
from shion.behavior import BELLY_LIFT_DISTANCE, TICKLE_SPEECH_SECONDS, TICKLE_STOP_SECONDS
from shion.pet_window import (DRAG_THRESHOLD, MARGIN_BOTTOM, MARGIN_TOP, MARGIN_X, MASK_GROW,
                              PetWindow)
from shion.v3_display import (REST_POSE, STATE_EXPRESSIONS, arms_for, V2_FOOT_GAP_RATIO, StateMotion,
                              desired_side, draw_key, expression_for, frame_interval, hair_moving,
                              logical_scale, state_pose)
from shion import v3_scene
from shion.v3_layers import SwayEnvelope, affine_ok, render_affine
from shion.v3_prewarm import BLINK_LEVELS, Prewarmer, quantize_eye
from shion.v3_scene_view import SceneImages, SceneOverlay, V3SleepZ, local_origin

RENDERER_CACHE = 2  # 每侧最多两份（换屏 DPR 来回不重建）
AUTO_SIDE_ENV = "SHION_V3_AUTO_SIDE"  # 换边默认打开（S8 起用画好的右鼓素材）；设为 0 固定左鼓
SIDE_STABLE_SECONDS = 0.5   # 位置/尺寸/屏幕连续这么久不变、也没在互动，才算“停稳”
SIDE_IDLE_RELEASE = 300.0   # 换走后旧侧闲置这么久就释放（rig、渲染器、预热缓存）
SIDE_SWAP_AT = 0.05         # 眨眼开始后这么久（闭眼最深在 0.06 秒）换边
SIDE_POP = 0.3              # 换边后新侧鼓脸颊“啵”：先按捏脸最大值的 30% 外拉，再由松手弹簧弹回
SIDE_PADDING = 48  # rig 像素：头发摆动、倾斜时不被裁掉
BELLY_HINT_DISTANCE = BELLY_LIFT_DISTANCE  # 肚子上没在挠、拖出这么远：提示“要拎脸颊”
LIFT_UP = 12.0     # 逻辑像素：脸颊上向上超过这么多，且竖向 > LIFT_RATIO × 横向，才算拎起
LIFT_RATIO = 1.2
MASK_INTERVAL = 0.1  # 秒：遮罩最多 10 次/秒
MAX_DT = 0.25  # 秒：一帧最多推进这么久（隐藏/睡眠恢复后不按几分钟的 dt 逐子步追赶）
# 后台占锁时最多连续推迟这么多帧（约 50ms），之后主线程直接等锁现算。
# 不设上限的话，后台排着上百个预热任务时，要的素材排在队尾，界面会停在旧帧好几秒。
MAX_DEFERRED = 3
MASK_DRIFT_PX = 3.0  # 轮廓自上次遮罩漂过这么多像素就提前重建（遮罩外扩 MASK_GROW=4px）
PROGRAM_FAST_DEGREES_PER_SECOND = 8.0  # V2 程序动作：倾斜变化快于此用 60 FPS
PROGRAM_FAST_SCALE_PER_SECOND = 0.2    # 压扁/拉伸变化快于此用 60 FPS
SWAY_DEGREES = 2.0  # 轻摆满幅（原型默认值）
LEAD = 0.07  # 秒：眨眼、轻摆开始前提前提速
POSE_EASE_TAU = 0.12  # 秒：状态姿态切换的缓动时间常数（约 0.35 秒到位）
SCENE_CACHE = 6  # scene 图像缓存：三个 scene × 两种尺寸/DPR
MOUTH_RIG = (529.0, 588.5)  # rig 坐标：neutral 嘴部区域中心（rig.json expression_sources.neutral.regions.mouth）

_RIGS: dict[str, object] = {}
# 测试可换成同步执行器；None 表示共用的后台线程
PREWARM_EXECUTOR = None


def load_rig(side: str):
    """加载一侧的 rig 并算好可见范围、脚底（约 0.3 秒；不碰全局缓存，后台线程可用）。"""
    from v3proto.render import Rig
    from shion.v3_memory import compact_rig
    rig = compact_rig(Rig(cheek_side=side))
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


_QUIT_HOOKED = False


def _hook_quit() -> None:
    """应用退出时关掉后台预热线程（atexit 之外再保险一次，进程收尾前就停）。"""
    global _QUIT_HOOKED
    app = QGuiApplication.instance()
    if _QUIT_HOOKED or app is None:
        return
    app.aboutToQuit.connect(Prewarmer.shutdown_pool)
    _QUIT_HOOKED = True


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

    def __init__(self, *args, initial_side: str | None = None, **kwargs):
        self._v3_initial_side = initial_side
        # 给了 rng（截图/配图的固定种子）时，发丝轻摆的时刻也由它决定，同一个种子逐帧可重复；不消耗 rng，别处的随机序列不变。
        rng = kwargs.get("rng")
        self._v3_sway_seed = None if rng is None else hash(rng.getstate()) & 0xFFFFFFFF
        super().__init__(*args, **kwargs)

    # ---- 尺寸与渲染器 ----
    def _v3_setup(self) -> None:
        if getattr(self, "_v3_ready", False):
            return
        from v3proto.animation import Animator, Settings
        # 按屏幕位置换边：右鼓用 S8 画好的素材（assets/sprites/v3/right）。
        # 设环境变量 SHION_V3_AUTO_SIDE=0 可固定左鼓。
        self.auto_side = os.environ.get(AUTO_SIDE_ENV) != "0"
        # 启动时按存档位置先猜一侧（app.run 传入），免得先建左侧再丢掉；猜错了首次显示会纠正。
        initial = getattr(self, "_v3_initial_side", None)
        self._v3_side = initial if self.auto_side and initial in ("left", "right") else "left"
        self._v3_rig = shared_rig(self._v3_side)
        self._v3_geometry = None  # 窗口几何只按第一次加载的 rig 算，换边不改窗口
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
                          "affine": 0, "mesh": 0, "side_switches": 0, "deferred": 0, "gc_ms": 0.0}
        self._v3_gc_wait: list | None = None  # 丢掉一侧后待做的一次 GC：还在跑的后台任务（空表 = 马上可做）
        self._v3_deferred_run = 0  # 当前连续推迟了几帧
        self._v3_sway = None
        # 状态姿态（S6）：静态部分缓动；周期动作（点头/哈欠/画圈/咀嚼）直接叠加；
        # 换状态时把上一状态的周期动作余量交给 carry 衰减掉，不跳。
        self._v3_motion = StateMotion()
        self._v3_pose_static = None
        self._v3_pose_dynamic = REST_POSE
        self._v3_pose_carry = REST_POSE
        self._v3_pose_state = None
        self._v3_pose_weight = 1.0
        self._v3_pose = None
        self._v3_screen_hooked = False
        # 姿势变体（S9）：collapse / bed / desk 用整图（shion/v3_scene.py）。None = 不用（环境变量或没有资源）
        self._v3_scenes = v3_scene.load_metadata()
        self._v3_scene_w = 0.0
        self._v3_scene_shown = None       # 此刻显示的 Scene（被拎起/拖动/下落打断时为 None）
        self._v3_scene_since = 0.0        # 这个 scene 开始显示的时刻（进入弹跳用）
        self._v3_scene_pending = False    # 目标 scene 还在后台载入：先保持现在的画面
        self._v3_scene_popping = False    # 进入弹跳正在播
        self._v3_scene_left = False       # 这一帧刚离开 scene：站姿图必须马上画
        self._v3_scene_cache: OrderedDict[tuple, SceneImages] = OrderedDict()
        self._v3_scene_jobs: dict[tuple, object] = {}
        self._v3_scene_overlay = None
        self._v3_scene_sig = "off"
        self._v3_scene_affine = (1.0, 0.0)
        self._v3_scene_override = None    # 测试用：固定 (sy, angle)
        self._v3_scene_mask_affine = (1.0, 0.0)
        self._v3_scene_stars = None       # 金星的整幅透明图（有金星时每帧重画）
        self._v3_mask_pass = False
        self._v3_scene_load_ms: list[float] = []
        _hook_quit()
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
        self._v3_renderer = self._renderer_for(self._height, dpr)
        self._v3_prewarmer = self._v3_prewarmers[self._v3_cache_key(self._v3_side, self._height, dpr)]
        self._v3_scene_sig = "off"
        self._v3_scene_stars = None
        self._v3_scene_prewarm()
        self._v3_side_target = None  # 尺寸/DPR 变了：正在准备的另一侧作废，停稳后重来
        self._v3_side_job = None
        self._v3_side_blink = None
        self._v3_image = None
        self._v3_key = None
        self._v3_mask_force = True

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
        running = self._v3_gc_wait or []
        for key in [k for k in self._v3_renderers if k[0] == side]:
            self._v3_renderers.pop(key)
            running = running + self._v3_prewarmers.pop(key).close()
        self._v3_side_idle.pop(side, None)
        _RIGS.pop(side, None)
        # 刚丢掉的一侧可能还有后台任务拿着引用、加上 _locked() 的引用环：立刻 GC 没用，
        # 等任务结束且没在互动时再收一次（_v3_side_step）。
        self._v3_gc_wait = running

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
        if (self._v3_gc_wait is not None and all(f.done() for f in self._v3_gc_wait)
                and not self._v3_busy()):
            self._v3_gc_wait = None
            started = time.perf_counter()
            gc.collect()
            self._v3_stats["gc_ms"] = round((time.perf_counter() - started) * 1000, 1)
        if not self.auto_side or not self._v3_side_started:
            return
        if self._v3_scene_w > 0.0:      # 姿势变体（S9）期间冻结：不换边，取消正在准备的；回站姿停稳后再按原规则补换
            if self._v3_side_target is not None:
                self._v3_cancel_side()
            self._v3_side_geom = (self.x(), self.y(), self.width(), self.height(), round(self._v3_dpr, 4))
            self._v3_side_since = now
            self._v3_side_blink = None
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
        if self._v3_scene_overlay is not None:
            self._v3_scene_overlay.hide()
        super().hideEvent(e)

    def moveEvent(self, e) -> None:
        super().moveEvent(e)
        self._v3_scene_follow()

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
        """头顶中心（全局坐标）：按 rig 实际头顶算；姿势变体里用 scene 自己的头顶。"""
        got = self._v3_scene_active()
        if got is not None:
            local = self._v3_scene_local(got[0], got[0].head_top)
            return self.mapToGlobal(QPoint(round(local.x()), round(local.y() + self._sh * 0.04)))
        rig = self._v3_rig
        foot_y = rig.v3_foot[1]
        top = rig.v3_visible[1]
        gap = self._height * V2_FOOT_GAP_RATIO
        y = self.height() - MARGIN_BOTTOM - gap - (foot_y - top) * self._v3_scale
        return self.mapToGlobal(QPoint(self.width() // 2, round(y + self._sh * 0.04)))

    # ---- 每帧 ----
    def closeEvent(self, e) -> None:
        if hasattr(self, "_v3_side_job"):
            self._v3_cancel_side()
        for prewarmer in getattr(self, "_v3_prewarmers", {}).values():
            prewarmer.close()
        overlay = getattr(self, "_v3_scene_overlay", None)
        if overlay is not None:
            overlay.hide()
            overlay.deleteLater()
            self._v3_scene_overlay = None
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
                or self._drag_playback is not None
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
        f = self._without_v2_breath(f)
        shown = max(f.layers, key=lambda item: item[1])[0] if f.layers else f.sprite
        expression = expression_for(shown, self.sprite_name)
        if expression != self._v3_settings.expression or self.sprite_name != self._v3_mask_state:
            self._v3_mask_force = True
            self._v3_mask_state = self.sprite_name
        self._v3_settings.expression = expression
        dt = 0.0 if self._v3_clock is None else min(MAX_DT, max(0.0, now - self._v3_clock))
        self._v3_clock = now
        animator = self._v3_animator
        if self._v3_sway is None:
            self._v3_sway = SwayEnvelope(now, seed=self._v3_sway_seed)
        if animator.interaction_active:
            self._v3_sway.force(now)
        self._v3_settings.sway_degrees = SWAY_DEGREES * self._v3_sway.value(now)
        pose = animator.advance(dt)
        if animator.lift.active:
            pose.root_offset = (0.0, 0.0)  # 窗口自己在动；root_roll / 身体 / 手臂照常
        raw = pose  # 叠加状态姿态之前的原始姿态：scene 的呼吸、敲头、摸头从这里取
        pose, posing = self._v3_state_pose(pose, now, dt)
        scene_sig = self._v3_scene_update(now, f, raw)
        scene_w = self._v3_scene_w
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
                or any(pose.pinch_delta) or self._v3_scene_popping)
        still = affine_ok(pose)
        soon = (pose.eye_scale < 1 or 0 <= animator.blink_start - animator.time <= LEAD
                or self._v3_sway.until_start(now) <= LEAD or posing)
        interval = frame_interval(bool(fast), self.sprite_name, still, soon)
        if self._timer.interval() != interval:
            self._timer.setInterval(interval)
        frame_key = (round(f.sx / 0.002), round(f.sy / 0.002), round(f.angle / 0.1),
                     round(self._jump_offset * 4))
        key = draw_key(expression, pose, self.v3_texture_scale, frame_key, self._v3_settings.arms)
        self._sync_sleep_z(now, f)
        self._frame = f
        self._v3_pose = pose
        scene_same = scene_sig is not None and scene_sig == self._v3_scene_sig
        self._v3_scene_sig = scene_sig
        if scene_w >= 1.0:
            # scene 完全显示：站姿图不画（离开 scene 的第一帧必然重画）
            self._v3_key = None
            if scene_same:
                return
        else:
            if scene_same and key is not None and key == self._v3_key and self._v3_image is not None:
                return
            if (self._v3_image is not None and self._v3_deferred_run < MAX_DEFERRED
                    and not self._v3_scene_left      # 刚离开 scene：不能再留着进 scene 前的旧站姿图
                    and prewarmer.would_block(self._v3_settings, pose)):
                # 这一帧要现算的东西正被后台占着锁：先留着上一张图，下一 tick 再画，不让界面等锁。
                # V2 变换（_frame）照常更新，下面的遮罩也照常按“旧图 + 新变换”重建，和屏幕上一致。
                stats["deferred"] += 1
                self._v3_deferred_run += 1
            else:
                self._v3_deferred_run = 0
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

    # ---- 姿势变体（S9）：collapse / bed / desk 的整图，规则见 shion/v3_scene.py ----
    def _v3_scene_key(self, scene) -> tuple:
        return (scene.name, self._height, round(self._v3_dpr, 4))

    def _v3_scene_prewarm(self) -> None:
        """后台把三个 scene 的数组算好（读图、缩放、预乘）；QImage 在主线程建。"""
        self._v3_scene_jobs.clear()
        if not self._v3_scenes:
            return
        executor = PREWARM_EXECUTOR or Prewarmer._shared_pool()
        scale = self._v3_scale * self._v3_dpr
        for scene in dict.fromkeys(self._v3_scenes.values()):
            key = self._v3_scene_key(scene)
            if key not in self._v3_scene_cache:
                self._v3_scene_jobs[key] = executor.submit(v3_scene.load_arrays, scene, scale)

    def _v3_scene_store(self, scene, arrays) -> SceneImages:
        key = self._v3_scene_key(scene)
        images = SceneImages(scene, arrays, self._v3_dpr)
        cache = self._v3_scene_cache
        cache[key] = images
        cache.move_to_end(key)
        while len(cache) > SCENE_CACHE:
            cache.popitem(last=False)
        return images

    def _v3_scene_drop(self, scene) -> None:
        """这个 scene 载入失败：以后不再用它，状态回到站姿回退姿态。"""
        left = {k: v for k, v in (self._v3_scenes or {}).items() if v is not scene}
        self._v3_scenes = left or None

    def _v3_scene_images(self, scene) -> SceneImages | None:
        """这个 scene 在当前尺寸/DPR 下的图像。
        缓存里有就取；后台做好了就收下；后台还在做就不等（_v3_scene_pending = True，返回 None，界面不卡）；
        没有后台任务（缓存被挤掉、预热关了）才同步载入这一个。载入失败：以后不再用这个 scene。"""
        key = self._v3_scene_key(scene)
        hit = self._v3_scene_cache.get(key)
        if hit is not None:
            self._v3_scene_cache.move_to_end(key)
            return hit
        job = self._v3_scene_jobs.get(key)
        arrays = None
        if job is not None:
            if not job.done():
                self._v3_scene_pending = True
                return None
            del self._v3_scene_jobs[key]
            try:
                arrays = job.result()
            except Exception:
                arrays = None
        if arrays is None:
            t0 = time.perf_counter()
            try:
                arrays = v3_scene.load_arrays(scene, self._v3_scale * self._v3_dpr)
            except Exception:
                self._v3_scene_drop(scene)
                return None
            self._v3_scene_load_ms.append(round((time.perf_counter() - t0) * 1000, 1))
        return self._v3_scene_store(scene, arrays)

    def _v3_scene_collect(self) -> None:
        """后台算好的 scene 数组转成图像放进缓存（每帧最多一个，不卡界面）。"""
        for key, job in list(self._v3_scene_jobs.items()):
            if not job.done():
                continue
            del self._v3_scene_jobs[key]
            scene = next((sc for sc in (self._v3_scenes or {}).values() if self._v3_scene_key(sc) == key), None)
            if scene is None or job.cancelled():
                continue
            try:
                arrays = job.result()
            except Exception:
                continue
            self._v3_scene_store(scene, arrays)
            return

    def _v3_scene_interrupted(self) -> bool:
        """拎起、拖动、下落、跳跃、拖动回放：scene 不淡化，直接切回站姿。"""
        return (self._v3_lifting or self._dragging or self._falling or self._jump_start is not None
                or self._drag_playback is not None)

    def _v3_set_width(self, width: int) -> None:
        """改窗口宽度，脚底中心不动（照 PetWindow._refresh 里 V2 床的做法）。"""
        if width == self._sw:
            return
        feet_x = self.x() + self.width() / 2
        old_pos = self.pos()
        self._sw = width
        self.setFixedSize(width + 2 * MARGIN_X, self.height())
        self.move(round(feet_x - self.width() / 2), self.y())
        self.clamp_position()
        if self._press_global is not None:
            self._grab_offset += old_pos - self.pos()
        self._v3_mask_force = True
        self.moved.emit()

    def _v3_scene_update(self, now: float, f, raw):
        """每帧：显示哪个 scene、窗口宽度、覆盖窗、呼吸/敲头/摸头/进入弹跳的仿射、金星。
        scene 之间、scene 与站姿之间都是直接切换（不淡化：两个轮廓不同的图叠起来必然有叠影）；
        目标 scene 还在后台载入时先保持现在的画面。
        返回本帧 scene 的绘制签名："off" = 没有 scene；None = 每帧都要重画（有金星）。"""
        self._v3_scene_pending = False
        target = v3_scene.scene_for(self.sprite_name, self._v3_scenes)
        if target is not None and self._v3_scene_images(target) is None:
            # 还没载好（pending）就保持现在显示的；载入失败（scene 已被丢掉）就回站姿
            target = self._v3_scene_shown if self._v3_scene_pending else None
        shown = None if (target is None or self._v3_scene_interrupted()) else target
        previous, self._v3_scene_shown = self._v3_scene_shown, shown
        self._v3_scene_w = 1.0 if shown is not None else 0.0
        self._v3_scene_left = previous is not None and shown is None
        if shown is not previous:                           # 进入 / 换 / 离开：锚点、遮罩、金星坐标都变了
            self._v3_scene_since = now
            self._v3_mask_force = True
            self._v3_animator._star_bursts = ()              # 金星的坐标系换了
            self.moved.emit()                                # 气泡、粒子的锚点换了：让控制器重新取
        pop = v3_scene.enter_pop(now - self._v3_scene_since) if shown is not None else 1.0
        self._v3_scene_popping = pop != 1.0
        w = self._v3_scene_w
        if shown is None:
            self._v3_scene_stars = None
            if self._v3_scene_overlay is not None and self._v3_scene_overlay.isVisible():
                self._v3_scene_overlay.set_scene(None, None, 0.0, False)
            if self._sw != self.normal_width:
                self._v3_set_width(self.normal_width)
            if not self._v3_scene_interrupted():
                self._v3_scene_collect()
            return "off"
        images = self._v3_scene_images(shown)
        if images is None:                                  # 刚被挤出缓存又没后台任务：同步载入失败
            self._v3_scene_w, self._v3_scene_shown = 0.0, None
            return "off"
        self._v3_set_width(max(self.normal_width, math.ceil(2 * v3_scene.extra_half_width(shown) * self._v3_scale)))
        sy, angle = v3_scene.scene_affine(shown, raw.body_scale, raw.head_y, raw.head_roll,
                                          v3_scene.poke_scale(f.sy), pop)
        if self._v3_scene_override is not None:
            sy, angle = self._v3_scene_override
        self._v3_scene_affine = (sy, angle)
        # 遮罩要跟得上缩回/倾斜：自上次建遮罩漂过 MASK_DRIFT_PX 就重建
        mask_sy, mask_angle = self._v3_scene_mask_affine
        s = self._v3_scale
        drift = (abs(sy - mask_sy) * (shown.ground_y - shown.char_box[1]) * s
                 + math.radians(abs(angle - mask_angle)) * 0.5 * shown.size[0] * s)
        if drift > MASK_DRIFT_PX:
            self._v3_mask_force = True
        stars = bool(raw.star_effects)
        self._v3_scene_stars = self._v3_scene_paint_stars(shown, images, raw) if stars else None
        self._v3_scene_place(shown, images, w)
        return v3_scene.scene_draw_key(shown, w, sy, angle, self.v3_texture_scale, stars)

    def _v3_scene_paint_stars(self, scene, images, raw):
        from v3proto.stars import paint_stars
        image = QImage(images.size[0], images.size[1], QImage.Format.Format_RGBA8888_Premultiplied)
        image.fill(0)
        foot = self._v3_rig.v3_foot
        offset = (images.pad + scene.anchor_x - foot[0], images.pad + scene.ground_y - foot[1])
        return paint_stars(image, self._v3_rig, images.scale, raw, offset=offset)

    def _v3_scene_place(self, scene, images, w: float) -> None:
        """家具覆盖窗：只在有家具的 scene 里显示；位置按诗音窗口的静止换算（不跟 V2 压扁/倾斜）。"""
        overlay = self._v3_scene_overlay
        if images.furniture is None:
            if overlay is not None:
                overlay.set_scene(None, None, 0.0, False)
            return
        if overlay is None:
            overlay = self._v3_scene_overlay = SceneOverlay(self)
        s = self._v3_scale
        origin = local_origin(self, scene, s, images.pad)
        rw, rh = images.rig_size
        rect = QRectF(self.x() + origin.x(), self.y() + origin.y(), rw * s, rh * s)
        overlay.set_scene(images.furniture, rect, w, bool(self.windowFlags() & Qt.WindowStaysOnTopHint))

    def _v3_scene_follow(self) -> None:
        """窗口移动时家具覆盖窗跟着走。"""
        scene = getattr(self, "_v3_scene_shown", None)
        overlay = getattr(self, "_v3_scene_overlay", None)
        if scene is None or overlay is None or not overlay.isVisible():
            return
        images = self._v3_scene_cache.get(self._v3_scene_key(scene))
        if images is not None:
            self._v3_scene_place(scene, images, self._v3_scene_w)

    # ---- 状态姿态（S6）----
    def _v3_state_pose(self, pose, now: float, dt: float):
        """叠加状态姿态；返回 (新 pose, 是否还在动)。互动期间整体淡出，结束后淡回。"""
        self._animator.whole_nod = False  # 工作点头由 V3 只动头来做，V2 不再整图点头
        state = self.sprite_name
        static = state_pose(state)
        if v3_scene.scene_for(state, self._v3_scenes) is not None:
            # 有整图姿势时，站姿只在淡入淡出和被拎起时露面：保持原样，不套“瘫倒/趴桌”的回退姿态
            static = replace(REST_POSE, breath_rate=static.breath_rate, blink_gap=static.blink_gap)
        motion = self._v3_motion
        if state != self._v3_pose_state:
            self._v3_pose_carry = self._v3_pose_carry + self._v3_pose_dynamic
            self._v3_pose_state = state
        dynamic = motion.sample(state, now)
        a = 1.0 if self._v3_pose_static is None else (1.0 - math.exp(-dt / POSE_EASE_TAU) if dt > 0 else 0.0)
        current = self._v3_pose_static if self._v3_pose_static is not None else static
        current = current.moved_toward(static, a)
        self._v3_pose_static = current
        self._v3_pose_carry = self._v3_pose_carry.moved_toward(REST_POSE, a)
        self._v3_pose_dynamic = dynamic
        target_w = 0.0 if self._v3_animator.interaction_active else 1.0
        w = self._v3_pose_weight + (target_w - self._v3_pose_weight) * a
        if abs(w - target_w) < 1e-3:
            w = target_w
        self._v3_pose_weight = w
        settings = self._v3_settings
        settings.breath_rate, settings.blink_gap = static.breath_rate, static.blink_gap
        settings.arms = arms_for(state)
        offset = (current + dynamic + self._v3_pose_carry).scaled(w)
        moving = (current != static or self._v3_pose_carry != REST_POSE
                  or w != target_w or motion.busy(state, now))
        return offset.apply(pose), moving

    def start_chewing(self, seconds: float) -> None:
        """喂零食：点头咀嚼 seconds 秒。"""
        self._v3_motion.chew(self._clock(), seconds)

    def mouth_anchor(self) -> QPoint:
        """嘴部中心（全局坐标）：跟随低头、点头和 V2 的压扁/倾斜/跳跃。"""
        got = self._v3_scene_active()
        if got is not None:
            local = self._v3_scene_local(got[0], got[0].mouth)
            return self.mapToGlobal(QPoint(round(local.x()), round(local.y())))
        f = getattr(self, "_frame", None)
        pose = self._v3_pose
        if f is None or pose is None:
            return super().mouth_anchor()
        from v3proto.motion import pivot_matrix, translation
        head = translation(pose.head_x, pose.head_y) @ pivot_matrix(self._v3_rig.pivots["neck"], pose.head_roll)
        rx, ry, _ = head @ np.array([MOUTH_RIG[0], MOUTH_RIG[1], 1.0])
        foot_x, foot_y = self._v3_rig.v3_foot
        s = self._v3_scale
        gap = self._height * V2_FOOT_GAP_RATIO
        local = QPointF((rx - foot_x) * s, (ry - foot_y) * s - gap)
        p = self._v3_transform(f).map(local)
        return self.mapToGlobal(QPoint(round(p.x()), round(p.y())))

    def v3_sleep_z_anchor(self, state: str):
        """睡觉 Z 的出发点（全局坐标）。只有床上睡（bed）的姿势变体有自己的锚点；其余返回 None，走 V2 的。"""
        scene = self._v3_scene_shown
        if (state != "bed" or scene is None or scene.name != "bed" or scene.z_anchor is None
                or self._v3_scene_w <= 0.0):
            return None
        local = self._v3_scene_local(scene, scene.z_anchor)
        return self.mapToGlobal(QPoint(round(local.x()), round(local.y())))

    def _sync_sleep_z(self, now: float, frame) -> None:
        """同父类，只是 Z 窗换成能用 scene 锚点的 V3SleepZ。"""
        state = ("bed" if frame.sprite.startswith("bed_") else "sleep" if frame.sprite == "sleep" else None)
        if (self.sprite_name not in ("sleep", "bed") or self.motion_active
                or self._dragging or self._falling or self.is_pressed):
            state = None
        if self._sleep_z is None:
            if state is None:
                return
            from shion.pet_window import SPRITE_DIR
            from shion.windowing import set_topmost
            self._sleep_z = V3SleepZ(self, SPRITE_DIR / "fx_z.png")
            set_topmost(self._sleep_z, bool(self.windowFlags() & Qt.WindowStaysOnTopHint))
        self._sleep_z.advance(now, state)

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

    # ---- 姿势变体里的命中、锚点（S9）----
    def _v3_scene_active(self):
        """scene 已经显示到可以点、可以对话的程度（权重 ≥ 0.5）→ (Scene, SceneImages)，否则 None。"""
        scene = self._v3_scene_shown
        if scene is None or self._v3_scene_w <= 0.0:
            return None
        images = self._v3_scene_cache.get(self._v3_scene_key(scene))
        return None if images is None else (scene, images)

    def _v3_scene_local(self, scene, point) -> QPointF:
        """scene 像素（静止图）→ 窗口坐标（逻辑像素）。静止位置，不含呼吸/晃动。"""
        s = self._v3_scale
        o = local_origin(self, scene, s, 0.0)
        return QPointF(o.x() + point[0] * s, o.y() + point[1] * s)

    def _v3_scene_hit(self, got, pos):
        """窗口坐标 → (区域, rig 点)：先撤销呼吸/摸头的仿射回到静止图，再查角色遮罩和 cheek/crown 椭圆。
        家具像素不在角色遮罩里，返回 None（也点穿，见 _update_mask）。"""
        scene, images = got
        s = self._v3_scale
        o = local_origin(self, scene, s, 0.0)
        sy, angle = self._v3_scene_affine
        x, y = v3_scene.to_rest(scene, ((pos.x() - o.x()) / s, (pos.y() - o.y()) / s), sy, angle)
        zone = v3_scene.zone_at(scene, x, y, v3_scene.ArrayMask(images.alpha, images.scale, images.pad))
        return zone, np.array(v3_scene.to_rig(scene, (x, y), self._v3_rig.v3_foot))

    def _v3_hit(self, pos):
        got = self._v3_scene_active()
        if got is not None:
            zone, point = self._v3_scene_hit(got, QPointF(pos))
            return zone, point, point
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
        if e.button() != Qt.LeftButton:
            return  # 右键/中键不打断正在进行的左键手势（拎起、捏脸、摸头、挠痒）
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
            # 姿势变体里没有站姿的脸颊曲面：拎起用默认支点；横拉捏脸不响应（见 mouseMoveEvent）
            self._v3_press_point = None if self._v3_scene_active() is not None else point
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
            if self._v3_scene_active() is not None:     # 姿势变体：不捏脸，拖远了只提示“捏着脸往上提”
                if distance > DRAG_THRESHOLD:
                    self._v3_idle_moved = True
                    self._v3_notify_ignored()
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
        self._v3_scene_cut()      # 姿势变体：立刻切回站姿（不淡化），窗口恢复站姿宽度
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

    def _v3_scene_cut(self) -> None:
        """拎起前：scene 不淡化，直接收掉（权重 0、家具窗隐藏、窗口宽度恢复、金星清掉）。"""
        if self._v3_scene_w <= 0.0 and self._sw == self.normal_width:
            return
        self._v3_scene_w = 0.0
        self._v3_scene_shown = None
        self._v3_scene_stars = None
        self._v3_animator._star_bursts = ()
        if self._v3_scene_overlay is not None:
            self._v3_scene_overlay.set_scene(None, None, 0.0, False)
        self._v3_set_width(self.normal_width)
        self._v3_mask_force = True
        self._v3_key = None

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
        if e.button() != Qt.LeftButton:
            super().mouseReleaseEvent(e)
            return  # 非左键松开：左键手势照常继续
        if kind is None or self._press_global is None:
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
            else:
                consumed = self._v3_idle_moved     # 姿势变体里横拉过：不算点击
        elif kind == "crown":
            pos = (e.position().x(), e.position().y())
            delta = self._v3_head_gesture.move(pos, True)
            if delta:
                a.stroke_head(delta)
            patting = self._v3_head_gesture.patting
            if self._v3_head_gesture.release():
                scene = self._v3_scene_active()
                if scene is not None:     # 姿势变体：金星落在点中的位置，左右按 scene 的头顶判断
                    point = self._v3_scene_hit(scene, QPointF(e.position()))[1]
                    neck_x = v3_scene.to_rig(scene[0], scene[0].head_top, self._v3_rig.v3_foot)[0]
                else:
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

    # ---- 截图（家具在覆盖窗里，普通的 render_frame 只有诗音窗口那一层）----
    def render_frame(self, scale: int = 1) -> QImage:
        if self._v3_scene_w > 0.0:
            return self.render_scene_frame(scale, clip=False)
        return super().render_frame(scale)

    def render_scene_frame(self, scale: int = 1, *, clip: bool = True) -> QImage:
        """诗音窗口 ∪ 家具覆盖窗合成的整幅画面（验收图和测试用）。clip=True 时按窗口遮罩裁剪，
        和屏幕上实际看到的一致（家具层本来就在遮罩外，由覆盖窗画）。"""
        union = self.rect()
        overlay = self._v3_scene_overlay
        local = None
        if overlay is not None and overlay.isVisible() and overlay.image is not None:
            local = overlay.geometry().translated(-self.pos())
            union = union.united(local)
        image = QImage(union.size() * scale, QImage.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(scale)
        image.fill(0)
        pet = QImage(self.size() * scale, QImage.Format_ARGB32_Premultiplied)
        pet.setDevicePixelRatio(scale)
        pet.fill(0)
        q = QPainter(pet)
        q.setRenderHints(QPainter.SmoothPixmapTransform | QPainter.Antialiasing)
        self._draw_sprite(q, self._frame)
        q.end()
        p = QPainter(image)
        p.translate(-union.topLeft())
        p.setRenderHints(QPainter.SmoothPixmapTransform | QPainter.Antialiasing)
        region = getattr(self, "_v3_region", None)
        if clip and region is not None:
            p.setClipRegion(region)
        p.drawImage(QPointF(0, 0), pet)
        p.setClipping(False)
        if local is not None:
            p.setOpacity(overlay.opacity)
            p.drawImage(overlay.image_rect().translated(local.x(), local.y()), overlay.image)
        p.end()
        return image

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
        self._v3_mask_pass = True   # 遮罩：站姿全不透明；scene 只含变形后的角色和家具缝带，不含家具
        self._v3_scene_mask_affine = self._v3_scene_affine
        try:
            self._draw_sprite(p, self._frame)
        finally:
            self._v3_mask_pass = False
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
        w = self._v3_scene_w
        if self._v3_image is not None and w < 1.0:
            rig = self._v3_rig
            foot_x, foot_y = rig.v3_foot
            s = self._v3_scale
            p.save()
            if w > 0.0 and not self._v3_mask_pass:
                p.setOpacity(1.0 - w)          # 淡入淡出：站姿淡出
            p.translate(self.width() / 2, self.height() - MARGIN_BOTTOM - self._jump_offset)
            p.rotate(f.angle)
            p.scale(f.sx, f.sy)
            gap = self._height * V2_FOOT_GAP_RATIO
            p.drawImage(QPointF(-foot_x * s, -gap - foot_y * s), self._v3_image)
            p.restore()
        if w > 0.0:
            self._draw_scene(p, w)

    def _draw_scene(self, p: QPainter, w: float) -> None:
        """姿势变体：整张场景图（静止）垫底 → 变形的角色层 → 金星。家具层在覆盖窗里，不在这里画。
        遮罩那一遍只画变形后的角色和家具缝带（家具本体不进遮罩，点得穿）。"""
        scene = self._v3_scene_shown
        images = self._v3_scene_cache.get(self._v3_scene_key(scene)) if scene is not None else None
        if images is None:
            return
        s = self._v3_scale
        origin = local_origin(self, scene, s, images.pad)
        rw, rh = images.rig_size
        rect = QRectF(origin.x(), origin.y(), rw * s, rh * s)
        sy, angle = self._v3_scene_affine
        gap = self._height * V2_FOOT_GAP_RATIO
        px, py = self.width() / 2, self.height() - MARGIN_BOTTOM - gap    # 地面线上的 anchor 点
        mask = self._v3_mask_pass
        p.save()
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if not mask:
            p.setOpacity(w)
            if images.under is not None:
                p.drawImage(rect, images.under)                         # 垫底：只有家具颜色，不动
        elif images.seam is not None:
            p.drawImage(rect, images.seam)                              # 遮罩：家具边上的静止缝带
        p.translate(px, py)
        p.rotate(angle)
        p.scale(1.0, sy)
        p.translate(-px, -py)
        p.drawImage(rect, images.char)                                  # 角色层：呼吸、敲头、摸头
        p.restore()
        if self._v3_scene_stars is not None and not mask:
            p.save()
            p.setOpacity(w)
            p.drawImage(rect, self._v3_scene_stars)
            p.restore()


__all__ = ["V3PetWindow", "shared_rig", "MARGIN_X", "MARGIN_TOP"]
