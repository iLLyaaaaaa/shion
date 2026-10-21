"""程序动画：呼吸、眨眼、压扁弹回、晃动、倾斜。

纯 Python，不 import Qt。时间通过参数传入（单位：秒，单调递增的浮点数）。
所有缩放、旋转都以脚底中心为锚点，由界面层负责做变换。
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from shion.behavior import PropPlayback

BREATH_STATES = {"idle", "neglect1"}
BREATH_PERIOD = 3.0
BREATH_AMP = 0.025  # sy 在 1.000 ~ 1.025 之间
WORKING_BREATH_AMP = 0.008
WORKING_BREATH_PERIOD = 4.0
WORKING_NOD_INTERVAL = (3.0, 5.0)
WORKING_NOD_DURATION = 0.4
WORKING_NOD_COMPRESSION = 0.015
WORKING_NOD_ANGLE = 1.0
NEGLECT_SWAY_AMP = 1.2
NEGLECT_SWAY_PERIOD = 3.5
CALM_BREATH_AMP = 0.012  # 其余固定表情沿用原来的轻呼吸

IDLE_SWAY_AMP = 1.5
IDLE_SWAY_PERIOD = 4.5
IDLE_SWAY_FADE = 0.3
WEIGHT_INTERVALS = {"normal": (8.0, 15.0), "lively": (5.0, 10.0)}
WEIGHT_DURATION = 0.6
WEIGHT_ANGLE = 3.0
WEIGHT_CROUCH = 0.02
WEIGHT_REBOUND = 0.006
WEIGHT_CROUCH_PORTION = 0.65

BLINK_MIN, BLINK_MAX = 3.0, 6.0
BLINK_DURATION = 0.120
DOUBLE_BLINK_CHANCE = 0.15
DOUBLE_BLINK_GAP = 0.150  # 第一次眨眼结束到第二次开始
TRANSITION = 0.120

SQUASH = {  # kind -> (时长 s, 最扁 sy)
    "click": (0.20, 0.92),
    "land": (0.25, 0.88),
    "switch": (0.24, 0.97),
    "step": (0.08, 0.97),
    "jump_land": (0.25, 0.84),
}

SWAY = {  # 状态 -> (幅度 度, 周期 s)
    "dizzy": (5.0, 0.9),
    "happy": (2.5, 0.6),
}

TILT_MAX = 12.0
TILT_GAIN = 0.015  # 度 / (px/s)
TILT_TAU = 0.08


@dataclass(frozen=True)
class Frame:
    sprite: str
    sx: float = 1.0
    sy: float = 1.0
    angle: float = 0.0  # 度，顺时针为正
    layers: tuple[tuple[str, float], ...] = ()  # 交叉淡化的图片及权重（总和为 1）


def ease_out(t: float) -> float:
    """三次 ease-out；所有调用都按经过的秒数归一化，不累计帧数。"""
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


def squash_scale(kind: str, elapsed: float) -> float:
    """压扁曲线，返回 sy。结束后精确为 1.0。

    前 60%：1 → 最扁 → 回到 1；后 40%：轻微反弹（拉长，幅度为压扁的 30%）再回到 1。
    """
    dur, low = SQUASH[kind]
    if elapsed <= 0 or elapsed >= dur:
        return 1.0
    p = elapsed / dur
    depth = 1.0 - low
    if p < 0.6:
        q = p / 0.6
        return 1.0 - depth * math.sin(math.pi * q)
    q = (p - 0.6) / 0.4
    return 1.0 + 0.3 * depth * math.sin(math.pi * q)


class IdleLife:
    """独立的待机姿态时间线；不改变状态/交互计时，错过的微动作不补播。"""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.context = None
        self.start = 0.0
        self.next_at = math.inf
        self.active = (-math.inf, "crouch", 1)

    def configure(self, now: float, enabled: bool, level: str) -> None:
        context = (enabled, level)
        if context == self.context:
            return
        self.context = context
        self.start = now
        self.active = (-math.inf, "crouch", 1)
        self.next_at = (now + self.rng.uniform(*WEIGHT_INTERVALS[level])
                        if enabled and level in WEIGHT_INTERVALS else math.inf)

    def sample(self, now: float) -> tuple[float, float]:
        if not self.context or not self.context[0]:
            return 1.0, 0.0
        elapsed = max(0.0, now - self.start)
        fade = math.sin(min(1.0, elapsed / IDLE_SWAY_FADE) * math.pi / 2) ** 2
        angle = IDLE_SWAY_AMP * math.sin(2 * math.pi * elapsed / IDLE_SWAY_PERIOD) * fade
        while self.next_at <= now:
            at = self.next_at
            self.active = (at, self.rng.choice(("crouch", "lean")), self.rng.choice((-1, 1)))
            self.next_at = at + self.rng.uniform(*WEIGHT_INTERVALS[self.context[1]])
        at, kind, side = self.active
        p = (now - at) / WEIGHT_DURATION
        if not 0 < p < 1:
            return 1.0, angle
        pulse = math.sin(math.pi * p) ** 2
        if kind == "lean":
            # 接管慢摇摆，峰值严格为 ±3°，两端位置和速度连续。
            return 1.0, angle * (1 - pulse) + side * WEIGHT_ANGLE * pulse
        if p < WEIGHT_CROUCH_PORTION:
            sy = 1 - WEIGHT_CROUCH * math.sin(math.pi * p / WEIGHT_CROUCH_PORTION) ** 2
        else:
            sy = 1 + WEIGHT_REBOUND * math.sin(math.pi * (p - WEIGHT_CROUCH_PORTION) / (1 - WEIGHT_CROUCH_PORTION)) ** 2
        return sy, angle


class Animator:
    def __init__(self, rng: random.Random | None = None):
        self._rng = rng or random.Random()
        self._state = "idle"
        self._t0 = 0.0
        # 眨眼：下一次眨眼开始的时间；以及当前眨眼区间（可能有第二次）
        self._next_blink = 0.0
        self._blinks: list[tuple[float, float]] = []
        # 压扁
        self._squash_kind: str | None = None
        self._squash_t0 = 0.0
        # 倾斜
        self._dragging = False
        self._tilt = 0.0
        self._tilt_target = 0.0
        self._tilt_t = 0.0
        self._initialized = False
        self._from_layers: tuple[tuple[str, float], ...] = ()
        self._from_pose: Frame | None = None
        self.calm = False
        self._props = PropPlayback(self._rng)
        # 随机流独立，微动作不改变眨眼/道具的随机时间线。
        life_rng = random.Random()
        life_rng.setstate(self._rng.getstate())
        self._idle_life = IdleLife(life_rng)
        nod_rng = random.Random()
        nod_rng.setstate(self._rng.getstate())
        self._nod_rng = nod_rng
        self._nod_enabled = False
        self._next_nod = math.inf
        self._nod_at = -math.inf
        self.idle_enabled = True
        self.activity_level = "normal"

    # ---- 状态 ----
    @property
    def state(self) -> str:
        return self._state

    def set_state(self, name: str, now: float, *, immediate: bool = False) -> None:
        if self._initialized and name == self._state and not immediate:
            return
        previous = self.frame(now) if self._initialized and not immediate else None
        self._from_layers = (previous.layers or ((previous.sprite, 1.0),)) if previous else ()
        self._from_pose = previous
        self._state = name
        if name in ("bed", "desk"):
            self._props.reset(now)
        self._t0 = now
        self._blinks = []
        self._schedule_blink(now)
        if previous:
            self.squash(now, "switch")
        elif immediate:
            self._squash_kind = None
        self._initialized = True
        self._nod_enabled = False
        self._next_nod = math.inf
        self._nod_at = -math.inf
        self._configure_idle(now)
        self._configure_nod(now)

    def _configure_idle(self, now: float) -> None:
        self._idle_life.configure(now, self._state == "idle" and not self.calm
                                  and not self._dragging and self.idle_enabled
                                  and self.activity_level != "quiet", self.activity_level)

    def _schedule_blink(self, now: float) -> None:
        self._next_blink = now + self._rng.uniform(BLINK_MIN, BLINK_MAX)

    def _configure_nod(self, now: float) -> None:
        # working 在控制器中本来就设 calm；轻点头仍保留，动作层/按住/拖动时取消。
        enabled = self._state == "working" and self.idle_enabled and not self._dragging
        if enabled != self._nod_enabled:
            self._nod_enabled = enabled
            self._nod_at = -math.inf
            self._next_nod = now + self._nod_rng.uniform(*WORKING_NOD_INTERVAL) if enabled else math.inf

    def _nod_sample(self, now: float) -> float:
        self._configure_nod(now)
        while self._next_nod <= now:
            self._nod_at = self._next_nod
            self._next_nod += self._nod_rng.uniform(*WORKING_NOD_INTERVAL)
        p = (now - self._nod_at) / WORKING_NOD_DURATION
        return math.sin(math.pi * p) ** 2 if self._nod_enabled and 0 < p < 1 else 0.0

    # ---- 压扁 ----
    def squash(self, now: float, kind: str) -> None:
        if kind not in SQUASH:
            raise ValueError(f"未知压扁类型：{kind}")
        self._squash_kind = kind
        self._squash_t0 = now

    # ---- 倾斜 ----
    def set_drag(self, dragging: bool, now: float | None = None) -> None:
        if now is not None:
            self._update_tilt(now)
        self._dragging = dragging
        if not dragging:
            self._tilt_target = 0.0

    def feed_velocity(self, vx: float, now: float) -> None:
        """拖动时每帧喂入水平速度（px/s）。向右拖 → 身体向左倾（顺时针为正，所以取负）。"""
        if not self._dragging:
            return
        self._update_tilt(now)
        self._tilt_target = max(-TILT_MAX, min(TILT_MAX, -vx * TILT_GAIN))

    def _update_tilt(self, now: float) -> None:
        dt = max(0.0, now - self._tilt_t)
        self._tilt_t = now
        if dt > 0:
            k = 1.0 - math.exp(-dt / TILT_TAU)
            self._tilt += (self._tilt_target - self._tilt) * k
        if abs(self._tilt) < 1e-3 and self._tilt_target == 0.0:
            self._tilt = 0.0

    # ---- 眨眼 ----
    def _blinking(self, now: float) -> bool:
        if self._state != "idle":
            return False
        # 消费错过的事件，用预定时刻排下一次，掉帧不会推迟整条时间线。
        while now >= self._next_blink:
            start = self._next_blink
            end = start + BLINK_DURATION
            self._blinks = [(start, end)]
            if self._rng.random() < DOUBLE_BLINK_CHANCE:
                s2 = end + DOUBLE_BLINK_GAP
                self._blinks.append((s2, s2 + BLINK_DURATION))
            last_end = self._blinks[-1][1]
            self._schedule_blink(last_end)
        if self._blinks:
            if now >= self._blinks[-1][1] + TRANSITION:
                self._blinks = []
            else:
                return any(a <= now < b for a, b in self._blinks)
        return False

    def _layers(self, now: float) -> tuple[tuple[str, float], ...]:
        current = {self._props.sprite(self._state, now) if self._state in ("bed", "desk") else self._state: 1.0}
        if self._state == "idle":
            for start, end in self._blinks:
                if start <= now < end + TRANSITION:
                    alpha = ease_out((now - start) / TRANSITION) if now < end else 1.0 - ease_out((now - end) / TRANSITION)
                    current = {"idle": 1.0 - alpha, "blink": alpha}
                    break
        mix = ease_out((now - self._t0) / TRANSITION) if self._from_layers else 1.0
        weights: dict[str, float] = {}
        for sprite, weight in self._from_layers:
            weights[sprite] = weights.get(sprite, 0.0) + weight * (1.0 - mix)
        for sprite, weight in current.items():
            weights[sprite] = weights.get(sprite, 0.0) + weight * mix
        return tuple((sprite, weight) for sprite, weight in weights.items() if weight > 1e-9)

    # ---- 合成 ----
    def frame(self, now: float) -> Frame:
        sprite = "blink" if self._blinking(now) else self._state
        if self._state in ("bed", "desk"):
            sprite = self._props.sprite(self._state, now)
        sy = 1.0
        sx = 1.0
        angle = 0.0

        if self._state not in ("bed", "desk") and (self._state in BREATH_STATES or self._state == "working" or self.calm):
            t = now - self._t0
            amp = BREATH_AMP if self._state in BREATH_STATES else CALM_BREATH_AMP
            period = BREATH_PERIOD
            if self._state == "working":
                amp, period = WORKING_BREATH_AMP, WORKING_BREATH_PERIOD
            sy *= 1.0 + (amp / 2) * (1.0 - math.cos(2 * math.pi * t / period))

        self._configure_idle(now)
        life_sy, life_angle = self._idle_life.sample(now)
        sy *= life_sy
        sx /= math.sqrt(life_sy)
        angle += life_angle

        nod = self._nod_sample(now)
        sy *= 1 - WORKING_NOD_COMPRESSION * nod
        angle += WORKING_NOD_ANGLE * nod

        if (self._state == "neglect2" and not self.calm and not self._dragging
                and self.idle_enabled and self.activity_level != "quiet"):
            angle += NEGLECT_SWAY_AMP * math.sin(math.tau * (now - self._t0) / NEGLECT_SWAY_PERIOD)

        if self._state in SWAY and not self.calm:
            amp, period = SWAY[self._state]
            angle += amp * math.sin(2 * math.pi * (now - self._t0) / period)

        self._update_tilt(now)
        angle += self._tilt
        if self._from_pose is not None:
            mix = ease_out((now - self._t0) / TRANSITION)
            sx = self._from_pose.sx + (sx - self._from_pose.sx) * mix
            sy = self._from_pose.sy + (sy - self._from_pose.sy) * mix
            angle = self._from_pose.angle + (angle - self._from_pose.angle) * mix

        if self._squash_kind is not None:
            dur = SQUASH[self._squash_kind][0]
            el = now - self._squash_t0
            if el >= dur:
                self._squash_kind = None
            else:
                s = squash_scale(self._squash_kind, el)
                sy *= s
                sx *= 1.0 / math.sqrt(s)

        return Frame(sprite, sx, sy, angle, self._layers(now))
