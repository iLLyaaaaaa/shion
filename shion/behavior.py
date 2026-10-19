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
IDLE_ACTIONS = ("turn", "face", "jump", "expression")
IDLE_ACTION_WEIGHTS = (1, 1, 1, 1)
IDLE_EXPRESSIONS = ("happy", "idle")
IDLE_EXPRESSION_WEIGHTS = (1, 1)
WALK_DURATION = 10.0
WALK_SPEED = 80.0
WALK_MIN_LEG = 40.0
WALK_HOP_HEIGHT = 10.0
WALK_HOP_PERIOD = 0.45
WALK_FRAME_SECONDS = 0.140
WALK_REFERENCE_SPEED = 80.0
WALK_BOB_HEIGHT = 3.0
WALK_BOB_FRAMES = 2  # 两帧一步，起伏随步频变化
JUMP_CROUCH_DURATION = 0.15
JUMP_AIR_DURATION = 0.4
JUMP_HEIGHT = 40.0
JUMP_DURATION = JUMP_CROUCH_DURATION + JUMP_AIR_DURATION
LEGACY_JUMP_HEIGHT = 18.0
LEGACY_JUMP_DURATION = 0.5


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


class Walk:
    """预先生成折线路径，采样只依赖经过时间，掉帧不会使行走变慢。"""

    def __init__(self, x: float, lo: float, hi: float, now: float, *,
                 cross: bool = False, rng: random.Random | None = None):
        rng = rng or random.Random()
        self.start = now
        self.speed = WALK_SPEED
        self.frame_seconds = WALK_FRAME_SECONDS * WALK_REFERENCE_SPEED / self.speed
        self.lo, self.hi = lo, max(lo, hi)
        x = max(self.lo, min(x, self.hi))
        self.points = [(0.0, x)]
        if cross:
            target = self.lo if x >= (self.lo + self.hi) / 2 else self.hi
            self.duration = abs(target - x) / self.speed
            self.points.append((self.duration, target))
        else:
            self.duration = WALK_DURATION
            t = 0.0
            while t < self.duration and self.hi > self.lo:
                target = rng.uniform(self.lo, self.hi)
                if abs(target - x) < WALK_MIN_LEG:
                    target = self.lo if x >= (self.lo + self.hi) / 2 else self.hi
                leg = abs(target - x) / self.speed
                end = min(t + leg, self.duration)
                x += (target - x) * ((end - t) / leg)
                self.points.append((end, x))
                t = end

    def sample(self, now: float) -> tuple[float, float, int, bool]:
        elapsed = max(0.0, now - self.start)
        finished = elapsed >= self.duration
        direction = 1
        x = self.points[-1][1]
        for (a, xa), (b, xb) in zip(self.points, self.points[1:]):
            direction = 1 if xb >= xa else -1
            if elapsed <= b:
                p = min(1.0, max(0.0, (elapsed - a) / (b - a))) if b > a else 1.0
                x = xa + (xb - xa) * p
                break
        jump = 0.0 if finished else WALK_HOP_HEIGHT * abs(math.sin(math.pi * elapsed / WALK_HOP_PERIOD))
        return max(self.lo, min(x, self.hi)), jump, direction, finished
