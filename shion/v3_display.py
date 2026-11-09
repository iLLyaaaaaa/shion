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
