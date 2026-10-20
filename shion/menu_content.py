"""内置对话数据；仅解析 JSON，动作只能来自白名单。"""
from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("shion.menu_content")
MENU_DIR = Path(__file__).resolve().parent.parent / "assets" / "menu"
MENU_EXPRESSIONS = {"happy", "proud", "stop", "dizzy", "idle", "neglect2"}


def translations(value) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {k: v for k, v in value.items() if isinstance(k, str) and isinstance(v, str) and v.strip()}


def localized(value: dict[str, str], lang: str) -> str:
    return value.get(lang) or value.get("zh", "")


@dataclass(frozen=True)
class Response:
    text: dict[str, str]
    expression: str | None = None


@dataclass(frozen=True)
class MenuItem:
    id: str
    name: dict[str, str]
    responses: tuple[Response, ...]
    action: str | None = None


class MenuContent:
    def __init__(self, directory: Path = MENU_DIR, rng: random.Random | None = None):
        self._rng = rng or random.Random()
        self._last: dict[tuple[str, str, str], int] = {}
        self.full: dict[str, str] = {}
        self.snacks = self._load(Path(directory) / "snacks.json", "snacks")
        self.talks = self._load(Path(directory) / "talks.json", "talks")

    def _load(self, path: Path, kind: str) -> tuple[MenuItem, ...]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or type(raw.get("schema_version")) is not int or raw["schema_version"] != 1:
                raise ValueError("不支持的菜单格式版本")
            if kind == "snacks":
                self.full = translations(raw.get("full_response"))
                if "zh" not in self.full:
                    raise ValueError("缺少吃饱回应")
            if not isinstance(raw.get("items"), list):
                raise ValueError("items 必须是列表")
        except (OSError, ValueError) as exc:
            log.warning("菜单不可用 %s：%s", path, exc)
            return ()
        out, seen = [], set()
        for item in raw["items"]:
            try:
                if not isinstance(item, dict):
                    raise ValueError("条目必须是对象")
                ident, name = item.get("id"), translations(item.get("name"))
                if not isinstance(ident, str) or not ident.strip() or ident in seen or "zh" not in name:
                    raise ValueError("无效或重复 id / 缺少中文名称")
                action = item.get("action")
                if action not in (None, "sleep") or kind == "snacks" and action is not None:
                    raise ValueError("未知动作")
                responses = []
                if not isinstance(item.get("responses"), list):
                    raise ValueError("responses 必须是列表")
                for response in item["responses"]:
                    if not isinstance(response, dict):
                        raise ValueError("回应必须是对象")
                    text = translations(response.get("text"))
                    expr = response.get("expression")
                    if "zh" not in text or expr is not None and (not isinstance(expr, str) or expr not in MENU_EXPRESSIONS):
                        raise ValueError("无效回应或表情")
                    responses.append(Response(text, expr))
                if not responses:
                    raise ValueError("没有回应")
                out.append(MenuItem(ident, name, tuple(responses), action))
                seen.add(ident)
            except (ValueError, TypeError) as exc:
                log.warning("跳过菜单条目 %s：%s", path, exc)
        return tuple(out)

    def find(self, kind: str, ident: str) -> MenuItem | None:
        return next((i for i in (self.snacks if kind == "snacks" else self.talks) if i.id == ident), None)

    def pick(self, kind: str, item: MenuItem, lang: str) -> Response:
        key = kind, item.id, lang
        choices = list(range(len(item.responses)))
        if len(choices) > 1 and key in self._last:
            previous = localized(item.responses[self._last[key]].text, lang)
            different = [i for i in choices if localized(item.responses[i].text, lang) != previous]
            choices = different or choices
        index = self._rng.choice(choices)
        self._last[key] = index
        return item.responses[index]
