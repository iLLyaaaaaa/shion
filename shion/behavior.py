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
TURN_FRAME_SECONDS = 0.090
FACE_SECONDS = 2.0
CHEEK_RELEASE_SECONDS = 2.0
CHEEK_LIFT_DISTANCE = 80.0
TICKLE_CLICK_WINDOW = 1.5
TICKLE_CLICK_COUNT = 3
TICKLE_STOP_SECONDS = 1.0
TICKLE_FRAME_SECONDS = 0.200
TICKLE_TWIST_DEGREES = 2.5
TICKLE_TWIST_PERIOD = 0.60
TICKLE_SPEECH_SECONDS = 4.0
BELLY_LIFT_DISTANCE = 40.0
RUB_DISTANCE = 8.0
RUB_REVERSALS = 2
RUB_WINDOW = 1.5
TICKLE_MOVE_DISTANCE = 2.0
JUMP_CROUCH_DURATION = 0.15
JUMP_RISE_DURATION = 0.09
JUMP_HOLD_DURATION = 0.20
JUMP_FALL_DURATION = 0.11
JUMP_AIR_DURATION = JUMP_RISE_DURATION + JUMP_HOLD_DURATION + JUMP_FALL_DURATION
JUMP_PHASES = (JUMP_CROUCH_DURATION, JUMP_RISE_DURATION, JUMP_HOLD_DURATION, JUMP_FALL_DURATION)
JUMP_CROUCH_DEPTH = 0.10
JUMP_HEIGHT = 45.0
JUMP_DURATION = JUMP_CROUCH_DURATION + JUMP_AIR_DURATION
LEGACY_JUMP_HEIGHT = 18.0
LEGACY_JUMP_DURATION = 0.5
DRAG_FRAME_SECONDS = 0.110
DRAG_MIN_FRAME_SECONDS = 0.060
DRAG_FAST_SPEED = 800.0
DRAG_RATE_TAU = 0.08
RELEASE_FAST_SPEED = 450.0  # px/s，达到此速度视为甩出
RELEASE_SAMPLE_SECONDS = 0.12
BED_FRAME_SECONDS = 0.9
DESK_BLINK_INTERVAL = (3.0, 6.0)
DESK_BLINK_SECONDS = 0.15
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

    def reset(self, now: float) -> None:
        self.start = now
        self.blink = now + self.rng.uniform(*DESK_BLINK_INTERVAL)
        self.sigh = now + self.rng.uniform(*DESK_SIGH_INTERVAL)
        self.active = ("desk_1", now)

    def sprite(self, state: str, now: float) -> str:
        if state == "bed":
            return f"bed_{int(max(0, now - self.start) / BED_FRAME_SECONDS + 1e-9) % 2 + 1}"
        while min(self.blink, self.sigh) <= now:
            if self.sigh <= self.blink:
                at = self.sigh
                self.active = ("desk_3", at + DESK_SIGH_SECONDS)
                self.sigh = at + self.rng.uniform(*DESK_SIGH_INTERVAL)
                self.blink = max(self.blink, self.active[1])
            else:
                at = self.blink
                self.active = ("desk_2", at + DESK_BLINK_SECONDS)
                self.blink = at + self.rng.uniform(*DESK_BLINK_INTERVAL)
        return self.active[0] if now < self.active[1] else "desk_1"


def jump_sample(elapsed: float) -> tuple[float, float, float]:
    """(升空高度, 四阶段归一化帧进度, sy)，与刷新次数无关。"""
    elapsed = max(0.0, elapsed)
    start = 0.0
    for stage, duration in enumerate(JUMP_PHASES):
        if elapsed + 1e-9 < start + duration:
            p = max(0.0, min(1.0, (elapsed - start) / duration))
            height = (0.0, JUMP_HEIGHT * (1 - (1 - p) ** 3),
                      JUMP_HEIGHT, JUMP_HEIGHT * (1 - p * p))[stage]
            sy = 1 - JUMP_CROUCH_DEPTH * math.sin(math.pi * p) if stage == 0 else 1.0
            return height, (stage + p) / len(JUMP_PHASES), sy
        start += duration
    return 0.0, 1.0, 1.0


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


class TickleGesture:
    """滑动点击窗口和有效往返；单向长拖或小抖动不会当成挠痒。"""

    def __init__(self):
        self.clicks: deque[float] = deque()
        self.begin_rub(0.0)

    def click(self, now: float) -> bool:
        while self.clicks and now - self.clicks[0] > TICKLE_CLICK_WINDOW + 1e-9:
            self.clicks.popleft()
        self.clicks.append(now)
        return len(self.clicks) >= TICKLE_CLICK_COUNT

    def begin_rub(self, x: float) -> None:
        self.extreme = x
        self.direction = 0
        self.reversals: deque[float] = deque()

    def rub(self, x: float, now: float) -> bool:
        delta = x - self.extreme
        if not self.direction:
            if abs(delta) >= RUB_DISTANCE:
                self.direction = 1 if delta > 0 else -1
                self.extreme = x
        elif delta * self.direction >= 0:
            self.extreme = x
        elif abs(delta) >= RUB_DISTANCE:
            self.direction *= -1
            self.extreme = x
            self.reversals.append(now)
        while self.reversals and now - self.reversals[0] > RUB_WINDOW + 1e-9:
            self.reversals.popleft()
        return len(self.reversals) >= RUB_REVERSALS
