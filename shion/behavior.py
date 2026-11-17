"""可注入时钟/随机数的行为逻辑，不依赖 Qt。距离均为 Qt 逻辑像素。"""
from __future__ import annotations

import math
import random
from collections import deque

SHAKE_DISTANCE = 40.0
SHAKE_WINDOW = 2.0
SHAKE_COUNT = 3
IDLE_INTERVALS = {"normal": (8.0, 20.0), "lively": (4.0, 10.0)}
IDLE_TALK_CHANCE = 0.10
IDLE_TALK_COOLDOWN = 60.0
IDLE_ACTIONS = ("jump", "expression")
IDLE_ACTION_WEIGHTS = (1, 2)
IDLE_EXPRESSIONS = ("happy", "idle")
IDLE_EXPRESSION_WEIGHTS = (1, 1)
TICKLE_STOP_SECONDS = 1.0
TICKLE_SPEECH_SECONDS = 4.0
BELLY_LIFT_DISTANCE = 40.0
JUMP_HEIGHT = 45.0  # 只用来给窗口顶部留出跳起的空间（MARGIN_TOP）；实际跳高是 LEGACY_JUMP_HEIGHT
LEGACY_JUMP_HEIGHT = 18.0
LEGACY_JUMP_DURATION = 0.5
DRAG_FRAME_SECONDS = 0.110
DRAG_MIN_FRAME_SECONDS = 0.060
DRAG_FAST_SPEED = 800.0
DRAG_RATE_TAU = 0.08
RELEASE_FAST_SPEED = 450.0  # px/s，达到此速度视为甩出
RELEASE_SAMPLE_SECONDS = 0.12
BED_FRAME_SECONDS = 0.9
DESK_BLINK_INTERVAL = (1.5, 3.5)
DESK_BLINK_SECONDS = 0.15
DESK_DOUBLE_BLINK_CHANCE = 0.20
DESK_DOUBLE_BLINK_GAP = 0.25  # 第一次闭眼结束到第二次开始
DESK_SIGH_INTERVAL = (10.0, 20.0)
DESK_SIGH_SECONDS = 1.2
NEGLECT_DESK_CHANCE = 0.35


class ReleaseVelocity:
    """取松手前一小段鼠标轨迹；停手后速度归零，不沿用最后一次移动速度。"""

    def __init__(self):
        self.samples = deque()

    def feed(self, now: float, x: float, y: float) -> None:
        if self.samples and now == self.samples[-1][0]:
            self.samples[-1] = (now, x, y)
        else:
            self.samples.append((now, x, y))
        while len(self.samples) > 2 and self.samples[1][0] <= now - RELEASE_SAMPLE_SECONDS:
            self.samples.popleft()

    def speed(self, now: float, x: float, y: float) -> float:
        self.feed(now, x, y)
        start, sx, sy = self.samples[0]
        cutoff = now - RELEASE_SAMPLE_SECONDS
        if len(self.samples) > 1 and start < cutoff:
            end, ex, ey = self.samples[1]
            p = min(1.0, (cutoff - start) / max(1e-9, end - start))
            sx, sy = sx + (ex - sx) * p, sy + (ey - sy) * p
            start = cutoff
        return math.hypot(x - sx, y - sy) / (now - start) if now > start else 0.0


class PropPlayback:
    """床和桌子的独立时间线；按预定时刻推进，掉帧不会延长眨眼或叹气。"""

    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.start = 0.0
        self.blink = self.sigh = math.inf
        self.active = ("desk_1", -math.inf)
        self.second_blink = math.inf

    def reset(self, now: float) -> None:
        self.start = now
        self.blink = now + self.rng.uniform(*DESK_BLINK_INTERVAL)
        self.sigh = now + self.rng.uniform(*DESK_SIGH_INTERVAL)
        self.active = ("desk_1", now)
        self.second_blink = math.inf

    def sprite(self, state: str, now: float) -> str:
        if state == "bed":
            return f"bed_{int(max(0, now - self.start) / BED_FRAME_SECONDS + 1e-9) % 2 + 1}"
        while min(self.blink, self.sigh, self.second_blink) <= now:
            if self.sigh <= min(self.blink, self.second_blink):
                at = self.sigh
                self.active = ("desk_3", at + DESK_SIGH_SECONDS)
                self.sigh = at + self.rng.uniform(*DESK_SIGH_INTERVAL)
                self.blink = max(self.blink, self.active[1])
                self.second_blink = math.inf
            elif self.second_blink <= self.blink:
                at = self.second_blink
                self.active = ("desk_2", at + DESK_BLINK_SECONDS)
                self.second_blink = math.inf
            else:
                at = self.blink
                self.active = ("desk_2", at + DESK_BLINK_SECONDS)
                self.blink = at + self.rng.uniform(*DESK_BLINK_INTERVAL)
                if self.rng.random() < DESK_DOUBLE_BLINK_CHANCE:
                    self.second_blink = at + DESK_BLINK_SECONDS + DESK_DOUBLE_BLINK_GAP
        return self.active[0] if now + 1e-9 < self.active[1] else "desk_1"


class DragPlayback:
    """连续相位；帧速率指数缓动，用解析积分避免掉帧改变播放进度。"""

    def __init__(self, now: float):
        self.time = now
        self.phase = 0.0
        self.rate = self.target_rate = 1 / DRAG_FRAME_SECONDS

    def advance(self, now: float) -> None:
        dt = max(0.0, now - self.time)
        self.time = max(self.time, now)
        decay = math.exp(-dt / DRAG_RATE_TAU)
        self.phase += self.target_rate * dt + (self.rate - self.target_rate) * DRAG_RATE_TAU * (1 - decay)
        self.rate = self.target_rate + (self.rate - self.target_rate) * decay

    def feed(self, now: float, speed: float, shakes: int) -> None:
        self.advance(now)
        strength = max(0.0, min(1.0, max(speed / DRAG_FAST_SPEED, shakes / SHAKE_COUNT)))
        seconds = DRAG_FRAME_SECONDS - (DRAG_FRAME_SECONDS - DRAG_MIN_FRAME_SECONDS) * strength
        self.target_rate = 1 / seconds

    def freeze(self, now: float) -> None:
        """松手时保持当前速率，后续下落和再次抓取都不重置相位。"""
        self.advance(now)
        self.target_rate = self.rate


class ShakeTracker:
    """反向后也走满阈值才确认转折，避免长距离移动后的 1px 抖动误算。"""

    def __init__(self):
        self.reset(0.0)

    def reset(self, x: float) -> None:
        self.extreme = x
        self.direction = 0
        self.marks: deque[float] = deque()
        self.shaken = False

    def feed(self, x: float, now: float) -> bool:
        delta = x - self.extreme
        if self.direction == 0:
            if abs(delta) > SHAKE_DISTANCE:
                self.direction = 1 if delta > 0 else -1
                self.extreme = x
        elif delta * self.direction >= 0:
            self.extreme = x
        elif abs(delta) > SHAKE_DISTANCE:
            self.direction *= -1
            self.extreme = x
            self.marks.append(now)
        while self.marks and now - self.marks[0] > SHAKE_WINDOW:
            self.marks.popleft()
        self.shaken |= len(self.marks) >= SHAKE_COUNT
        return self.shaken


class IdleBehavior:
    def __init__(self, rng: random.Random | None = None):
        self.rng = rng or random.Random()
        self.next_at: float | None = None
        self.last_talk = -math.inf
        self.level = None

    def step(self, now: float, eligible: bool, level: str) -> str | None:
        if not eligible or level not in IDLE_INTERVALS:
            self.next_at = None
            self.level = level
            return None
        if self.next_at is None or self.level != level:
            self.level = level
            self.next_at = now + self.rng.uniform(*IDLE_INTERVALS[level])
        if now < self.next_at:
            return None
        self.next_at = now + self.rng.uniform(*IDLE_INTERVALS[level])
        if now - self.last_talk >= IDLE_TALK_COOLDOWN and self.rng.random() < IDLE_TALK_CHANCE:
            self.last_talk = now
            return "talk"
        return self.rng.choices(IDLE_ACTIONS, weights=IDLE_ACTION_WEIGHTS, k=1)[0]
