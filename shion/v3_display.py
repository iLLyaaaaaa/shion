"""V3 纸偶显示的纯逻辑：正式状态 → V3 表情、纹理比例。不依赖 Qt。

正式状态机的名字和业务语义不变，这里只决定“画成什么样”。缺姿态的状态先用
现有 V3 表情回退（需新画清单见 docs/v3-integration-plan.md），不混用 V2 精灵图。
"""
from __future__ import annotations

# 底层状态 / 道具状态 → V3 表情
STATE_EXPRESSIONS = {
    "idle": "neutral",
    "working": "neutral",
    "neglect1": "neutral",
    "slump": "neutral",
    "happy": "happy",
    "done": "happy",
    "cheer": "happy",
    "proud": "smug",
    "stop": "angry",
    "dizzy": "dizzy",
    "neglect2": "teary",
    "yawn": "sleep",
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
