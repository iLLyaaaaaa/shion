"""工作遥控菜单里会话的显示名（纯 Python，不 import Qt）。

名字来自 hook 报来的工作目录文件夹名（server.clean_project 已校验）。
同一个文件夹有多个会话时，按出现顺序第 2 个起加 “(2)”“(3)”；
隐私模式（只显示状态，不显示内容）或拿不到文件夹名时，改用“会话 1 / 会话 2”这样的编号。
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional

MAX_KNOWN = 200  # 最多记住多少个会话（按出现顺序丢最早的），防止长时间运行无限增长


class SessionNames:
    def __init__(self) -> None:
        self._order: dict[str, int] = {}  # 会话 → 首次出现序号
        self._project: dict[str, str] = {}  # 会话 → 文件夹名
        self._seq = 0

    def note(self, session: Optional[str], project: Optional[str] = None) -> None:
        """收到带会话的事件时调用：记下首次出现顺序；带了文件夹名就更新。"""
        if not session:
            return
        if session not in self._order:
            self._seq += 1
            self._order[session] = self._seq
            if len(self._order) > MAX_KNOWN:
                oldest = min(self._order, key=self._order.get)
                self._order.pop(oldest)
                self._project.pop(oldest, None)
        if project:
            self._project[session] = project

    def forget_all(self) -> None:
        self._order.clear()
        self._project.clear()

    def project(self, session: str) -> Optional[str]:
        return self._project.get(session)

    def ordered(self, sessions: Iterable[str]) -> list[str]:
        """去重、去掉空值，按首次出现顺序排（没见过的排最后，保持传入顺序）。"""
        unique = [s for s in dict.fromkeys(sessions) if s]
        big = len(self._order) + self._seq + 1
        return sorted(unique, key=lambda s: (self._order.get(s, big), unique.index(s)))

    def labels(self, sessions: Iterable[str], private: bool, ui: Callable[..., str]) -> dict[str, str]:
        """{会话: 显示名}。sessions 是这一刻菜单要列出的会话。"""
        ordered = self.ordered(sessions)
        out: dict[str, str] = {}
        seen: dict[str, int] = {}
        for n, s in enumerate(ordered, 1):
            name = None if private else self._project.get(s)
            if not name:
                out[s] = ui("session_n", n=n)
                continue
            seen[name] = seen.get(name, 0) + 1
            out[s] = name if seen[name] == 1 else f"{name} ({seen[name]})"
        return out
