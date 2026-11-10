"""V3 纸偶显示的纯逻辑：正式状态 → V3 表情、纹理比例。不依赖 Qt。

正式状态机的名字和业务语义不变，这里只决定“画成什么样”。缺姿态的状态先用
现有 V3 表情回退（需新画清单见 docs/v3-integration-plan.md），不混用 V2 精灵图。
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace


# 底层状态 / 道具状态 → V3 表情
STATE_EXPRESSIONS = {
    "idle": "neutral",
    "working": "neutral",
    "neglect1": "bored",   # S6：S0 部件拼的无聊脸（tools/v3_s0_faces.py）
    "slump": "tired",      # S6：S0 部件拼的疲惫半闭眼
    "happy": "happy",
    "done": "happy",
    "cheer": "happy",
    "proud": "smug",
    "stop": "angry",
    "dizzy": "dizzy",
    "neglect2": "teary",
    "yawn": "yawn",        # S6：sleep 眼 + 放大 1.8 倍的 S0 张大嘴
    "collapse": "sleep",
    "sleep": "sleep",
    "bed": "sleep",
    "desk": "sleep",
    "drag": "surprised",  # S4 换成拎起反应
}
# 序列帧前缀 → V3 表情；None 表示沿用底层状态的表情
SEQUENCE_EXPRESSIONS = {
    "cheek": "angry",
    "tickle": "happy",
    "drag": "surprised",
    "bed": "sleep",
    "desk": "sleep",
    "jump": None,
}
# 不换表情的帧：V3 自己会眨眼
FOLLOW_BASE = {"blink"}

# V2 精灵 idle.png 不透明区域高度 / 画布高度（448×512 画布，y 24..503）
V2_VISIBLE_RATIO = 480 / 512
# V2 画布里脚底以下的透明高度占比（脚底在 y=503，画布底 512）
V2_FOOT_GAP_RATIO = 8 / 512


def expression_for(sprite: str, base: str) -> str:
    """当前画出的 V2 帧名 sprite、底层状态 base → V3 表情。"""
    base_expression = _state_expression(base)
    if sprite in FOLLOW_BASE:
        return base_expression
    if sprite in STATE_EXPRESSIONS:
        return STATE_EXPRESSIONS[sprite]
    prefix, sep, number = sprite.partition("_")
    if sep and number.isdigit() and prefix in SEQUENCE_EXPRESSIONS:
        mapped = SEQUENCE_EXPRESSIONS[prefix]
        return base_expression if mapped is None else mapped
    raise ValueError(f"没有 V3 显示映射：{sprite}")


def _state_expression(base: str) -> str:
    if base in FOLLOW_BASE:
        return "neutral"
    if base not in STATE_EXPRESSIONS:
        raise ValueError(f"没有 V3 显示映射：{base}")
    return STATE_EXPRESSIONS[base]


def logical_scale(height: int, v3_visible_height: float) -> float:
    """每个 rig 像素对应多少逻辑像素：V3 可见高度对齐 V2 同档精灵的可见高度。"""
    return height * V2_VISIBLE_RATIO / v3_visible_height


def texture_scale(height: int, dpr: float, v3_visible_height: float) -> float:
    """纹理按实际显示高度 × DPR 生成（单位：设备像素 / rig 像素）。"""
    return logical_scale(height, v3_visible_height) * dpr


# ---- 帧节奏 ----
FAST_MS = 16   # 互动、程序动作、头发还在摆
CALM_MS = 33   # 待机、工作：只剩呼吸和眨眼
SLEEP_MS = 66  # 睡着
SLEEPY_STATES = {"sleep", "bed", "desk", "collapse"}
# 待机时头发一直在轻轻摆（约 ±2°，每秒几度），30 FPS 足够；被拨动、甩动时才
# 需要 60 FPS。按角速度判断，而不是“有没有在动”。
HAIR_FAST_DEGREES_PER_SECOND = 12.0


STILL_MS = 66          # 头发静止的待机、睡着：15 FPS
WORKING_STILL_MS = 50  # 头发静止的工作：20 FPS


def frame_interval(fast: bool, state: str, still: bool = False, soon: bool = False) -> int:
    """fast：互动/程序动作/头发大幅摆动；still：走仿射路径（头发静止）；
    soon：正在眨眼或即将眨眼/开始轻摆，临时 30 FPS。"""
    if fast:
        return FAST_MS
    if state in SLEEPY_STATES:
        return SLEEP_MS
    if still and not soon:
        return WORKING_STILL_MS if state == "working" else STILL_MS
    return CALM_MS


def hair_moving(previous: dict | None, angles: dict, dt: float) -> bool:
    """任一摆动角的角速度超过 12°/秒，算头发正在大幅摆动。"""
    if previous is None or dt <= 0:
        return False
    keys = set(previous) | set(angles)
    limit = HAIR_FAST_DEGREES_PER_SECOND * dt
    return any(abs(angles.get(k, 0.0) - previous.get(k, 0.0)) > limit for k in keys)


_ANGLE_STEP = 0.1
_RATIO_STEP = 0.02


def _q(value: float, step: float) -> int:
    return round(value / step)


def draw_key(expression: str, pose, texture_scale: float, frame_key: tuple):
    """量化后的“这一帧长什么样”；与上一帧相同就不必重画。

    位移量化到 0.25 设备像素，角度到 0.1°，比例/进度到 0.02。
    有金星特效时返回 None（特效每帧都在动）。
    """
    if pose.star_effects:
        return None
    position = 0.25 / max(texture_scale, 1e-6)
    return (
        expression, frame_key,
        _q(pose.body_scale, 0.25 / 300), _q(pose.head_x, position), _q(pose.head_y, position),
        _q(pose.eye_scale, _RATIO_STEP), _q(pose.head_roll, _ANGLE_STEP),
        tuple(sorted((k, _q(v, _ANGLE_STEP)) for k, v in pose.angles.items())),
        tuple(_q(v, position) for v in pose.pinch_delta),
        pose.reaction_face, pose.reaction_base, _q(pose.reaction_fade, _RATIO_STEP),
        _q(pose.arm_degrees, _ANGLE_STEP), _q(pose.leg_degrees, _ANGLE_STEP),
        _q(pose.body_roll, _ANGLE_STEP), _q(pose.root_roll, _ANGLE_STEP),
        tuple(_q(v, position) for v in pose.root_offset),
    )


# ---- 换边（S5）----
SIDE_DEAD_FRACTION = 0.05  # 中线两侧死区：可用宽度的 5%
SIDE_DEAD_MIN = 40         # 至少 40 逻辑像素


def desired_side(center_x: float, avail_left: float, avail_width: float, current: str) -> str:
    """窗口中心在可用区域右半边 → 鼓左脸颊（"left"，朝屏幕中间）；左半边 → 鼓右脸颊（"right"）。
    中线两侧死区内保持当前侧。"""
    middle = avail_left + avail_width / 2
    dead = max(SIDE_DEAD_FRACTION * avail_width, SIDE_DEAD_MIN)
    if center_x > middle + dead:
        return "left"
    if center_x < middle - dead:
        return "right"
    return current


# ---- 状态姿态（S6）----
# 单位：head_x/head_y 是 rig 像素（y 向下为正，正 = 低头/下沉）；arm 是 Pose.arm_degrees
# （正 = 双臂向外抬，负 = 收向身体）；compress 是身体下压比例（头跟着脖子一起下沉）。
NECK_TO_HIP = 1063.4 - 664.0  # 与原型 breathing() 一致：身体压扁时脖子下沉的力臂


@dataclass(frozen=True)
class StatePose:
    head_x: float = 0.0
    head_y: float = 0.0
    head_roll: float = 0.0
    compress: float = 0.0
    arm: float = 0.0
    breath_rate: float = 1.0
    blink_gap: float = 1.0

    def __add__(self, other: "StatePose") -> "StatePose":
        return StatePose(self.head_x + other.head_x, self.head_y + other.head_y,
                         self.head_roll + other.head_roll, self.compress + other.compress,
                         self.arm + other.arm, self.breath_rate, self.blink_gap)

    def scaled(self, k: float) -> "StatePose":
        return StatePose(self.head_x * k, self.head_y * k, self.head_roll * k,
                         self.compress * k, self.arm * k, self.breath_rate, self.blink_gap)

    def moved_toward(self, target: "StatePose", a: float) -> "StatePose":
        """向 target 靠近 a（0～1）；差得很小就直接到位，免得没完没了地重画。"""
        def mix(x, y, snap):
            v = x + (y - x) * a
            return y if abs(y - v) < snap else v
        return StatePose(mix(self.head_x, target.head_x, .02), mix(self.head_y, target.head_y, .02),
                         mix(self.head_roll, target.head_roll, .005),
                         mix(self.compress, target.compress, 1e-5), mix(self.arm, target.arm, .005),
                         target.breath_rate, target.blink_gap)

    def apply(self, pose):
        """叠加到原型 Pose 上（返回新 Pose）。"""
        return replace(pose,
                       body_scale=pose.body_scale - self.compress,
                       head_x=pose.head_x + self.head_x,
                       head_y=pose.head_y + self.head_y + self.compress * NECK_TO_HIP,
                       head_roll=pose.head_roll + self.head_roll,
                       arm_degrees=pose.arm_degrees + self.arm)


REST_POSE = StatePose()
# 各状态的静态姿态。幅度是初值，按快照和真实窗口再调。
STATE_POSES = {
    "idle": REST_POSE,
    "blink": REST_POSE,
    "happy": REST_POSE,
    "done": REST_POSE,
    "cheer": REST_POSE,
    "proud": REST_POSE,
    "drag": REST_POSE,
    "working": StatePose(head_y=10),                                  # 头略低，看屏幕
    "neglect1": StatePose(head_y=18, breath_rate=.75, blink_gap=1.4),
    "neglect2": StatePose(head_y=18),
    "yawn": REST_POSE,                                                # 动作在 StateMotion 里
    "slump": StatePose(head_y=16, compress=.02, arm=-4, breath_rate=.8, blink_gap=1.3),
    "collapse": StatePose(head_y=30, compress=.04, arm=-6, breath_rate=.7, blink_gap=1.6),
    "sleep": StatePose(breath_rate=.7),
    "bed": StatePose(breath_rate=.7),
    "desk": StatePose(head_y=24, breath_rate=.7),
    "dizzy": REST_POSE,                                               # 画圈在 StateMotion 里
    "stop": StatePose(arm=8),                                         # 挡手占位，等新画
}

WORKING_NOD_INTERVAL = (4.0, 6.0)  # 秒
WORKING_NOD_DURATION = 0.5
WORKING_NOD_DEPTH = 10.0           # rig 像素
YAWN_INTERVAL = (6.0, 8.0)
YAWN_RISE, YAWN_HOLD, YAWN_FALL = 0.7, 1.0, 0.8
YAWN_STRETCH = StatePose(head_y=-8, compress=-.015, arm=8)
DIZZY_PERIOD = 1.0
DIZZY_RADIUS = (6.0, 4.0)          # 头部画圈的横、竖半径（rig 像素）
CHEW_HZ = 3.0
CHEW_DEPTH = 3.0


def _bump(p: float) -> float:
    """0→1→0，两端速度为 0。"""
    return math.sin(math.pi * p) ** 2 if 0 < p < 1 else 0.0


def _smooth01(u: float) -> float:
    u = min(1.0, max(0.0, u))
    return u * u * (3 - 2 * u)


class StateMotion:
    """状态自带的周期动作：工作点头、哈欠、晕头画圈、咀嚼。纯逻辑，时间由调用方给。"""

    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)
        self.state = None
        self.since = 0.0
        self.next_event = math.inf
        self.event_at = -math.inf
        self.chew_until = -math.inf

    def _interval(self, state: str):
        return {"working": WORKING_NOD_INTERVAL, "yawn": YAWN_INTERVAL}.get(state)

    def _sync(self, state: str, now: float) -> None:
        if state == self.state:
            return
        self.state, self.since = state, now
        self.event_at = -math.inf
        interval = self._interval(state)
        self.next_event = now + self.rng.uniform(*interval) if interval else math.inf

    def chew(self, now: float, seconds: float) -> None:
        self.chew_until = now + seconds

    def chewing(self, now: float) -> bool:
        return now < self.chew_until

    def _episode_length(self) -> float:
        return WORKING_NOD_DURATION if self.state == "working" else YAWN_RISE + YAWN_HOLD + YAWN_FALL

    def sample(self, state: str, now: float) -> StatePose:
        self._sync(state, now)
        while self.next_event <= now:
            self.event_at = self.next_event
            self.next_event += self.rng.uniform(*self._interval(state))
        out = REST_POSE
        elapsed = now - self.event_at
        if state == "working":
            out = StatePose(head_y=WORKING_NOD_DEPTH * _bump(elapsed / WORKING_NOD_DURATION))
        elif state == "yawn" and 0 <= elapsed < self._episode_length():
            if elapsed < YAWN_RISE:
                k = _smooth01(elapsed / YAWN_RISE)
            elif elapsed < YAWN_RISE + YAWN_HOLD:
                k = 1.0
            else:
                k = 1.0 - _smooth01((elapsed - YAWN_RISE - YAWN_HOLD) / YAWN_FALL)
            out = YAWN_STRETCH.scaled(k)
        elif state == "dizzy":
            a = math.tau * (now - self.since) / DIZZY_PERIOD
            # 从 0 起步：前半秒把半径渐入，不会一切进来就跳到圆周上
            r = _smooth01((now - self.since) / 0.5)
            out = StatePose(head_x=DIZZY_RADIUS[0] * math.sin(a) * r,
                            head_y=DIZZY_RADIUS[1] * (1 - math.cos(a)) * r)
        if self.chewing(now):
            out = out + StatePose(head_y=CHEW_DEPTH * (0.5 - 0.5 * math.cos(math.tau * CHEW_HZ * now)))
        return out

    def busy(self, state: str, now: float) -> bool:
        """此刻有周期动作在动（用来临时提到 30 FPS）。"""
        if state == "dizzy" or self.chewing(now):
            return True
        if state in ("working", "yawn"):
            elapsed = now - self.event_at
            return (0 <= elapsed < self._episode_length()) or 0 <= self.next_event - now <= 0.07
        return False


def state_pose(state: str) -> StatePose:
    if state not in STATE_POSES:
        raise ValueError(f"没有 V3 姿态：{state}")
    return STATE_POSES[state]
