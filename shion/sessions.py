"""工作遥控菜单里会话的显示名（纯 Python，不 import Qt）。

名字来自 hook 报来的工作目录文件夹名（server.clean_project 已校验）。
某个文件夹只有一个会话：只显示文件夹名。
同一个文件夹有多个会话：显示“文件夹名 · 第一句话摘要”；摘要也相同时再加“(2)”“(3)”；
还没收到第一句话的会话退回原来的编号（按该文件夹里的出现顺序，第 2 个起加“(2)”）。
隐私模式（只显示状态，不显示内容）或拿不到文件夹名时，改用“会话 1 / 会话 2”这样的编号。

第一句话摘要只存在内存里（这个对象里），不写日志、不进存档；隐私模式下不记录。
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional

MAX_KNOWN = 200  # 最多记住多少个会话（按出现顺序丢最早的），防止长时间运行无限增长
HEAD_CHARS = 12  # 摘要最多显示几个字符（中日文也按字符算），超出加“…”
LABEL_W = 240  # 菜单项 / 检查点面板里会话名的最大宽度（逻辑像素），超出截断，全文放 tooltip


def summarize(text: Optional[str]) -> str:
    """第一句话的摘要：压缩空白（换行等都算），取前 12 个字符，超出加“…”。"""
    if not isinstance(text, str):
        return ""
    text = " ".join(text.split())
    return text if len(text) <= HEAD_CHARS else text[:HEAD_CHARS] + "…"


class SessionNames:
    def __init__(self) -> None:
        self._order: dict[str, int] = {}  # 会话 → 首次出现序号
        self._project: dict[str, str] = {}  # 会话 → 文件夹名
        self._first: dict[str, str] = {}  # 会话 → 第一句话摘要（只在内存）
        self._seq = 0

    def note(self, session: Optional[str], project: Optional[str] = None,
             prompt_head: Optional[str] = None, private: bool = False) -> None:
        """收到带会话的事件时调用：记下首次出现顺序；带了文件夹名就更新；
        第一次带了提示词开头就记下摘要（之后的不覆盖）。private=True 时不记录提示词。"""
        if not session:
            return
        if session not in self._order:
            self._seq += 1
            self._order[session] = self._seq
            if len(self._order) > MAX_KNOWN:
                oldest = min(self._order, key=self._order.get)
                self._order.pop(oldest)
                self._project.pop(oldest, None)
                self._first.pop(oldest, None)
        if project:
            self._project[session] = project
        if not private and session not in self._first:
            head = summarize(prompt_head)
            if head:
                self._first[session] = head

    def forget_prompts(self) -> None:
        """丢掉所有已记的第一句话（打开隐私模式时调用）。"""
        self._first.clear()

    def forget_all(self) -> None:
        self._order.clear()
        self._project.clear()
        self._first.clear()

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
        names = {s: (None if private else self._project.get(s)) for s in ordered}
        per_folder: dict[str, int] = {}
        for name in names.values():
            if name:
                per_folder[name] = per_folder.get(name, 0) + 1
        out: dict[str, str] = {}
        seen: dict[str, int] = {}  # 文件夹名 → 已出现几个（没摘要时的编号，同原来）
        seen_head: dict[str, int] = {}  # “文件夹名 · 摘要” → 已出现几个
        for n, s in enumerate(ordered, 1):
            name = names[s]
            if not name:
                out[s] = ui("session_n", n=n)
                continue
            seen[name] = seen.get(name, 0) + 1
            head = self._first.get(s) if per_folder[name] > 1 else None
            if head:
                base = f"{name} · {head}"
                seen_head[base] = seen_head.get(base, 0) + 1
                out[s] = base if seen_head[base] == 1 else f"{base} ({seen_head[base]})"
            else:
                out[s] = name if seen[name] == 1 else f"{name} ({seen[name]})"
        return out
