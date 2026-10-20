"""“立即中断”：结束 CC 会话里正在跑的工具子进程（不 import Qt）。

做法：从进程表里找 CC 进程的直接子进程，只挑“创建时间晚于当前在执行的工具开始时间”的（MCP 服务器等
常驻子进程在会话开始时就有了，不会被误杀），排除 hook 进程（Shion 自己的 python 和 hook 报来的 pid），
把这些子进程连同它们的子孙一起结束。之后由 hub 的一次性中断标记让下一个检查点结束这一轮。

不发送 Ctrl+C：实测（2.1.289）向终端版 CC 的控制台发 GenerateConsoleCtrlEvent 会让 CC 整个退出。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from shion import winproc

log = logging.getLogger("shion.interrupt")

START_SLACK = 1.0  # 秒：工具开始时间取自收到 PreToolUse 事件的时刻，留一点余量


@dataclass
class CCProcess:
    """hook 报来的 CC 进程（见 hooks/shion_hook.py:find_cc_process）。"""

    pid: int
    created: int  # FILETIME
    name: str
    entry: str = ""
    hooks: list = field(default_factory=list)


@dataclass
class ProcessView:
    """进程表的查询接口；测试里换成假的。"""

    table: Callable[[], dict] = winproc.process_table
    created: Callable[[int], Optional[int]] = winproc.process_created
    image: Callable[[int], str] = winproc.process_image
    terminate: Callable[[int, Optional[int]], bool] = winproc.terminate


def is_alive(proc: CCProcess, view: ProcessView, table: Optional[dict] = None) -> bool:
    """CC 进程还在，名字和创建时间都对得上（PID 没被复用）。"""
    table = view.table() if table is None else table
    entry = table.get(proc.pid)
    return bool(entry) and entry[1].lower() == proc.name and view.created(proc.pid) == proc.created


def _descendants(table: dict, root: int) -> list[int]:
    """root 的所有子孙，深的在前（先结束孙进程，再结束子进程）。"""
    children: dict[int, list[int]] = {}
    for pid, (ppid, _) in table.items():
        if pid != ppid:
            children.setdefault(ppid, []).append(pid)
    order, stack, seen = [], [root], {root}
    while stack:
        pid = stack.pop()
        for child in children.get(pid, []):
            if child not in seen:
                seen.add(child)
                order.append(child)
                stack.append(child)
    return order[::-1]


def tool_processes(proc: CCProcess, tool_starts: list[float], view: ProcessView, table: dict,
                   hook_images: tuple[str, ...] = ()) -> list[int]:
    """要结束的 CC 直接子进程：工具开始之后才创建、且不是 hook。tool_starts 是 Unix 秒。"""
    if not tool_starts:
        return []
    since = min(tool_starts) - START_SLACK
    hooks = set(proc.hooks)
    images = {str(Path(p)).lower() for p in hook_images}
    picked = []
    for pid, (ppid, _) in table.items():
        if ppid != proc.pid or pid in hooks:
            continue
        created = view.created(pid)
        if created is None or winproc.filetime_to_unix(created) < since:
            continue
        if images and str(Path(view.image(pid) or "")).lower() in images:
            continue  # hook（exec 形式，CC 直接启动 .venv 里的 python）
        picked.append(pid)
    return sorted(picked)


def interrupt(proc: CCProcess, tool_starts: list[float], view: Optional[ProcessView] = None,
              hook_images: tuple[str, ...] = ()) -> Optional[list[int]]:
    """结束这个会话正在跑的工具进程树。CC 进程找不到（已退出、PID 被复用）返回 None；否则返回结束了的 pid。"""
    view = view or ProcessView()
    table = view.table()
    if not is_alive(proc, view, table):
        return None
    killed = []
    for top in tool_processes(proc, tool_starts, view, table, hook_images):
        top_created = view.created(top)
        for pid in _descendants(table, top) + [top]:
            created = view.created(pid)
            if created is None or (top_created is not None and created < top_created):
                continue  # 比父进程还早：PID 被复用了，不是这棵树里的
            if view.terminate(pid, created):
                killed.append(pid)
    log.info("立即中断：CC %s 结束了 %s", proc.pid, killed)
    return killed
