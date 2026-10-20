"""最近活动记录（只在内存里，不写存档）和把事件说成人话。不 import Qt。"""
from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

MAX_ENTRIES = 20
SHOW_RECENT = 5
TOOL_KINDS = ("read", "edit", "write", "bash", "search", "web", "agent", "other")


@dataclass(frozen=True)
class Entry:
    time: datetime
    kind: str  # 事件类型：session_start / working / stop / tool_error …
    tool: str = ""  # working 时的工具类别
    target: str = ""  # 文件名 / 搜索词 / 出错的工具名


def parse_working(detail: Optional[str]) -> Optional[tuple[str, str]]:
    """hook 发来的 working detail 是 JSON {"tool","target"}；解析失败返回 None。"""
    if not detail:
        return None
    try:
        d = json.loads(detail)
    except ValueError:
        return None
    if not isinstance(d, dict):
        return None
    tool, target = d.get("tool"), d.get("target")
    if tool not in TOOL_KINDS:
        tool = "other"
    return tool, target if isinstance(target, str) else ""


def make_entry(etype: str, detail: Optional[str], now: datetime) -> Optional[Entry]:
    if etype == "working":
        parsed = parse_working(detail)
        return Entry(now, etype, *(parsed or ("other", "")))
    if etype == "stop":
        return Entry(now, etype)  # 旧 hook 传来的回复内容也不保留
    if etype in ("session_start", "tool_error"):
        return Entry(now, etype, target=detail or "")
    return None  # prompt / notification / react 不进记录


def describe(entry: Entry, ui: Callable[..., str], private: bool) -> str:
    """一条记录的显示文字。隐私模式下不含文件名、搜索词。"""
    if entry.kind == "working":
        if private:
            return ui("act_private")
        if entry.target:
            return ui(f"act_{entry.tool}", target=entry.target)
        return ui("act_bash" if entry.tool == "bash" else "act_other")
    if entry.kind == "stop":
        return ui("act_done")
    if entry.kind == "tool_error":
        if entry.target and not private:
            return ui("act_error", target=entry.target)
        return ui("act_error_plain")
    return ui("act_start")


class ActivityLog:
    def __init__(self) -> None:
        self._items: deque[Entry] = deque(maxlen=MAX_ENTRIES)

    def add(self, entry: Optional[Entry]) -> None:
        if entry is not None:
            self._items.append(entry)

    def clear(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)

    def recent(self, n: int = SHOW_RECENT) -> list[Entry]:
        """最近 n 条，新的在前。"""
        return list(self._items)[::-1][:n]

    def recent_lines(self, ui: Callable[..., str], private: bool, n: int = SHOW_RECENT) -> list[str]:
        return [f"{e.time:%H:%M} {describe(e, ui, private)}" for e in self.recent(n)]
