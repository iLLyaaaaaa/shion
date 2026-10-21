"""数据驱动的好感规则。仅使用调用方传入的数据，不依赖 Qt 或系统时钟。"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path

AFFECTION_PATH = Path(__file__).resolve().parent.parent / "assets" / "affection.json"
log = logging.getLogger("shion.affection")


def integer(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError("无效整数")
    return value


def number(value, minimum=0, maximum=100):
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError("无效数值")
    return value


def trilingual(value):
    if not isinstance(value, dict) or any(not isinstance(value.get(k), str) or not value[k].strip()
                                          for k in ("zh", "en", "ja")):
        raise ValueError("缺少三语文字")
    return {k: value[k] for k in ("zh", "en", "ja")}


@dataclass(frozen=True)
class Level:
    threshold: int
    name: dict[str, str]
    upgrade: dict[str, str]
    poke_factor: float


@dataclass(frozen=True)
class AffectionRules:
    levels: tuple[Level, ...]
    daily: dict[str, dict[str, int]]
    rare_chance: float
    rare_cooldown: float

    def level(self, points: int) -> int:
        return sum(points >= item.threshold for item in self.levels)

    def probabilities(self, level: int, stop: float, dizzy: float) -> tuple[float, float]:
        factor = self.levels[max(1, min(level, len(self.levels))) - 1].poke_factor
        stop, dizzy = max(0.0, stop) * factor, max(0.0, dizzy) * factor
        total = stop + dizzy
        if total > 1:
            stop, dizzy = stop / total, dizzy / total
        return stop, dizzy


def load_rules(path: Path = AFFECTION_PATH) -> AffectionRules | None:
    """整个核心配置无效就禁用等级系统，保留原来的计数行为。"""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or type(raw.get("schema_version")) is not int or raw["schema_version"] != 1:
            raise ValueError("不支持的好感配置版本")
        items = raw["levels"]
        if not isinstance(items, list) or len(items) != 5:
            raise ValueError("必须有五个等级")
        levels = []
        for index, item in enumerate(items, 1):
            if integer(item["level"], 1) != index:
                raise ValueError("等级必须连续")
            levels.append(Level(integer(item["threshold"]), trilingual(item["name"]),
                                trilingual(item["upgrade"]), number(item["poke_factor"])))
        thresholds = [item.threshold for item in levels]
        if thresholds[0] != 0 or any(a >= b for a, b in zip(thresholds, thresholds[1:])):
            raise ValueError("阈值必须从零严格递增")
        daily = {}
        for source in ("pat", "snack", "talk", "open"):
            item = raw["daily"][source]
            daily[source] = {"amount": integer(item["amount"], 1), "limit": integer(item["limit"], 1)}
        # talk/open 的一次性语义不能被配置变成无限次。
        if daily["talk"]["limit"] != 1 or daily["open"]["limit"] != 1:
            raise ValueError("对话和打开必须每天一次")
        rare = raw["rare_idle"]
        return AffectionRules(tuple(levels), daily, number(rare["chance"], 0, 1),
                              number(rare["cooldown_seconds"], 1, 86400))
    except (OSError, ValueError, KeyError, TypeError, OverflowError) as exc:
        log.warning("好感等级不可用，回退为旧计数行为 %s：%s", path, exc)
        return None
