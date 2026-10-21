"""台词库与界面文字：从 assets/lines/<语言>.json 读取，缺的 key 回退到中文。

文件格式：{"meta": {"name", "font_fallback"}, "lines": {类别: [台词…]}, "ui": {key: 文字（可带 {占位符}）}}。
语言列表由扫描目录得到，新增语言只需放一个 json。同一类台词不连续重复。
"""
from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger("shion.lines")

LINES_DIR = Path(__file__).resolve().parent.parent / "assets" / "lines"
FALLBACK_LANG = "zh"
CURRENT_LEVEL_WEIGHT = 0.60
LEVELED_KEYS = {"pat", "neglect_return", "idle_talk"}


def _read(path: Path) -> dict:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning("读取语言文件失败 %s：%s", path, e)
        return {}
    return raw if isinstance(raw, dict) else {}


def _sub(raw: dict, key: str) -> dict:
    v = raw.get(key)
    return v if isinstance(v, dict) else {}


def available_languages(directory: Path = LINES_DIR) -> list[tuple[str, str]]:
    """扫描目录里的 *.json，返回 [(代码, 显示名)]；中文排第一，其余按代码排序。坏文件跳过。"""
    out = []
    try:
        files = sorted(Path(directory).glob("*.json"))
    except OSError:
        return []
    for p in files:
        raw = _read(p)
        if not raw:
            continue
        name = _sub(raw, "meta").get("name")
        out.append((p.stem, name if isinstance(name, str) and name else p.stem))
    out.sort(key=lambda t: (t[0] != FALLBACK_LANG, t[0]))
    return out


def resolve_language(saved: Optional[str], locale_name: str, codes: Iterable[str]) -> str:
    """存档里的语言可用就用它；否则跟随系统：zh→中文、ja→日文、其余→英文；目标不存在就回退中文。"""
    have = set(codes)
    if saved and saved in have:
        return saved
    prefix = (locale_name or "").replace("-", "_").split("_")[0].lower()
    want = prefix if prefix in ("zh", "ja") else "en"
    return want if want in have else FALLBACK_LANG


class Lines:
    def __init__(
        self,
        lang: str = FALLBACK_LANG,
        rng: Optional[random.Random] = None,
        directory: Path = LINES_DIR,
    ):
        self._rng = rng or random.Random()
        self._dir = Path(directory)
        self._last: dict[str, str] = {}
        self.lang = FALLBACK_LANG
        self._lines: dict[str, list] = {}
        self._ui: dict[str, str] = {}
        self._meta: dict = {}
        self.set_language(lang)

    def available_languages(self) -> list[tuple[str, str]]:
        return available_languages(self._dir)

    def set_language(self, lang: str) -> None:
        """切换语言；文件不存在或损坏就用中文。缺的 key 回退到中文。"""
        base = _read(self._dir / f"{FALLBACK_LANG}.json")
        cur = base
        if lang != FALLBACK_LANG:
            cur = _read(self._dir / f"{lang}.json")
            if not cur:
                log.warning("语言 %s 不可用，改用 %s", lang, FALLBACK_LANG)
                lang, cur = FALLBACK_LANG, base
        self.lang = lang
        self._last.clear()

        def pools(raw):
            return {
                k: [s for s in v if isinstance(s, str) or (
                    isinstance(s, dict) and isinstance(s.get("text"), str) and s["text"].strip()
                    and type(s.get("min_level", 1)) is int and 1 <= s.get("min_level", 1) <= 5)]
                for k, v in _sub(raw, "lines").items()
                if isinstance(v, list)
            }

        def strings(raw):
            return {k: v for k, v in _sub(raw, "ui").items() if isinstance(v, str)}

        self._lines = pools(base)
        self._lines.update({k: v for k, v in pools(cur).items() if v})
        self._ui = {**strings(base), **strings(cur)}
        self._meta = _sub(cur, "meta")

    @property
    def font_fallback(self) -> list[str]:
        v = self._meta.get("font_fallback")
        return [s for s in v if isinstance(s, str)] if isinstance(v, list) else []

    def keys(self) -> set[str]:
        return set(self._lines)

    def ui(self, key: str, **kw) -> str:
        text = self._ui.get(key, key)
        try:
            return text.format(**kw)
        except (KeyError, IndexError, ValueError):
            return text

    def _pool(self, key: str, level: int | None) -> list[str]:
        return [s if isinstance(s, str) else s["text"] for s in self._lines.get(key, [])
                if isinstance(s, str) or level is None or s.get("min_level", 1) <= level]

    def pick_for_level(self, key: str, level: int | None) -> Optional[str]:
        """先按池加权，再在池内等概率抽句；基础类别共用连续去重记录。"""
        if level is None or key not in LEVELED_KEYS:
            return self.pick(key, level)
        current = self._pool(f"{key}_level_{level}", level)
        others = [self._pool(f"{key}_level_{i}", level) for i in range(1, level)]
        others.append(self._pool(key, level))
        others = [pool for pool in others if pool]
        pools, weights = [], []
        if current:
            pools.append(current)
            weights.append(CURRENT_LEVEL_WEIGHT)
        for pool in others:
            pools.append(pool)
            weights.append((1 - CURRENT_LEVEL_WEIGHT) / len(others))
        # 排除上次的句子后再选池，避免重抽导致 60/40 的池权重偏移。
        last = self._last.get(key)
        filtered = [[text for text in pool if text != last] for pool in pools]
        candidates = [(pool, weight) for pool, weight in zip(filtered, weights) if pool]
        if not candidates:
            candidates = list(zip(pools, weights))  # 全部只有同一句时允许重复
        if not candidates:
            return None
        chosen = self._rng.choices([p for p, _ in candidates],
                                   weights=[w for _, w in candidates], k=1)[0]
        text = self._rng.choice(chosen)
        self._last[key] = text
        return text

    def pick(self, key: str, level: int | None = None) -> Optional[str]:
        pool = self._pool(key, level)
        if not pool:
            return None
        if len(pool) > 1 and key in self._last:
            pool = [s for s in pool if s != self._last[key]] or pool
        choice = self._rng.choice(pool)
        self._last[key] = choice
        return choice
