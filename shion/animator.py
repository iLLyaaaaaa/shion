"""程序动画：呼吸、眨眼、压扁弹回、晃动、倾斜。

纯 Python，不 import Qt。时间通过参数传入（单位：秒，单调递增的浮点数）。
所有缩放、旋转都以脚底中心为锚点，由界面层负责做变换。
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

BREATH_STATES = {"idle", "neglect1"}
BREATH_PERIOD = 3.0
BREATH_AMP = 0.012  # sy 在 1.000 ~ 1.012 之间

BLINK_MIN, BLINK_MAX = 3.0, 6.0
BLINK_DURATION = 0.120
DOUBLE_BLINK_CHANCE = 0.15
DOUBLE_BLINK_GAP = 0.150  # 第一次眨眼结束到第二次开始

SQUASH = {  # kind -> (时长 s, 最扁 sy)
    "click": (0.20, 0.92),
    "land": (0.25, 0.88),
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

    # ---- 状态 ----
    @property
    def state(self) -> str:
        return self._state

    def set_state(self, name: str, now: float) -> None:
        self._state = name
        self._t0 = now
        self._blinks = []
        self._schedule_blink(now)

    def _schedule_blink(self, now: float) -> None:
        self._next_blink = now + self._rng.uniform(BLINK_MIN, BLINK_MAX)

    # ---- 压扁 ----
    def squash(self, now: float, kind: str) -> None:
        if kind not in SQUASH:
            raise ValueError(f"未知压扁类型：{kind}")
        self._squash_kind = kind
        self._squash_t0 = now

    # ---- 倾斜 ----
    def set_drag(self, dragging: bool) -> None:
        self._dragging = dragging
        if not dragging:
            self._tilt_target = 0.0

    def feed_velocity(self, vx: float, now: float) -> None:
        """拖动时每帧喂入水平速度（px/s）。向右拖 → 身体向左倾（顺时针为正，所以取负）。"""
        if not self._dragging:
            return
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
        if not self._blinks and now >= self._next_blink:
            start = self._next_blink
            end = start + BLINK_DURATION
            self._blinks = [(start, end)]
            if self._rng.random() < DOUBLE_BLINK_CHANCE:
                s2 = end + DOUBLE_BLINK_GAP
                self._blinks.append((s2, s2 + BLINK_DURATION))
            last_end = self._blinks[-1][1]
            self._schedule_blink(last_end)
        if self._blinks:
            if now >= self._blinks[-1][1]:
                self._blinks = []
            else:
                return any(a <= now < b for a, b in self._blinks)
        return False

    # ---- 合成 ----
    def frame(self, now: float) -> Frame:
        sprite = "blink" if self._blinking(now) else self._state
        sy = 1.0
        sx = 1.0
        angle = 0.0

        if self._state in BREATH_STATES:
            t = now - self._t0
            sy *= 1.0 + (BREATH_AMP / 2) * (1.0 - math.cos(2 * math.pi * t / BREATH_PERIOD))

        if self._state in SWAY:
            amp, period = SWAY[self._state]
            angle += amp * math.sin(2 * math.pi * (now - self._t0) / period)

        if self._squash_kind is not None:
            dur = SQUASH[self._squash_kind][0]
            el = now - self._squash_t0
            if el >= dur:
                self._squash_kind = None
            else:
                s = squash_scale(self._squash_kind, el)
                sy *= s
                sx *= 1.0 / math.sqrt(s)

        self._update_tilt(now)
        angle += self._tilt
        return Frame(sprite, sx, sy, angle)
