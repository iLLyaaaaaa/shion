"""台词库：从 assets/lines/zh.json 随机抽取，同一类不连续重复。"""
from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Optional

log = logging.getLogger("shion.lines")

LINES_PATH = Path(__file__).resolve().parent.parent / "assets" / "lines" / "zh.json"


class Lines:
    def __init__(self, path: Path = LINES_PATH, rng: Optional[random.Random] = None):
        self._rng = rng or random.Random()
        self._last: dict[str, str] = {}
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            log.warning("读取台词失败：%s", e)
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        self._lines: dict[str, list[str]] = {
            k: [s for s in v if isinstance(s, str)]
            for k, v in raw.items()
            if isinstance(v, list)
        }

    def keys(self) -> set[str]:
        return set(self._lines)

    def pick(self, key: str) -> Optional[str]:
        pool = self._lines.get(key)
        if not pool:
            return None
        if len(pool) > 1 and key in self._last:
            pool = [s for s in pool if s != self._last[key]]
        choice = self._rng.choice(pool)
        self._last[key] = choice
        return choice
