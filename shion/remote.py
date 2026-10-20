"""工作遥控的线程安全共享状态（纯 Python，不 import Qt）。

服务线程（长轮询的 hook 请求）和 GUI 线程（用户点按钮）都会碰它，所以用一个 Condition 保护。
这里只存“暂停”之类的标志；谁能改它由调用方决定：HTTP 服务只读、只等，不替用户做决定。
"""
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

MAX_WAIT = 30.0  # 单次长轮询最多等多久（秒）


class RemoteHub:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._paused = False
        self._stop = False
        self.permissions = PermissionQueue()

    # ---- 暂停 / 继续 ----
    @property
    def is_paused(self) -> bool:
        with self._cond:
            return self._paused

    def pause(self) -> None:
        with self._cond:
            self._paused = True
            self._cond.notify_all()

    def resume(self) -> None:
        with self._cond:
            self._paused = False
            self._cond.notify_all()

    def wait_while_paused(self, seconds: float) -> bool:
        """最多等 seconds 秒，直到不再暂停。返回结束时是否仍在暂停。"""
        seconds = max(0.0, min(float(seconds), MAX_WAIT))
        with self._cond:
            self._cond.wait_for(lambda: not self._paused, timeout=seconds)
            return self._paused

    # ---- 停下（只生效一次） ----
    @property
    def stop_requested(self) -> bool:
        with self._cond:
            return self._stop

    def request_stop(self) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify_all()

    def cancel_stop(self) -> None:
        with self._cond:
            self._stop = False
            self._cond.notify_all()

    def wait_gate(self, seconds: float) -> tuple[bool, bool]:
        """检查点：最多等 seconds 秒，直到不再暂停或有人请求停下。返回 (仍在暂停, 这次要停下)。

        停下请求在这里被原子地取走：并行的多个 hook 只有一个会拿到，之后自动清除。
        停下不改变暂停标记。
        """
        seconds = max(0.0, min(float(seconds), MAX_WAIT))
        with self._cond:
            self._cond.wait_for(lambda: self._stop or not self._paused, timeout=seconds)
            stop, self._stop = self._stop, False
            return self._paused, stop


# ---------------------------------------------------------------- 授权请求
MAX_PENDING = 20  # 同时排队的授权请求上限，防止被灌满
DETAIL_MAX = 20000  # 命令/路径/计划全文的字数上限
TOOL_MAX = 60
PENDING_IDLE = 25.0  # 请求超过这么久没被 hook 轮询，就认为 hook 已经没了（用户在 CC 里自己答了）
DECIDED_KEEP = 60.0  # 已有决定但没人来取的请求，保留多久


@dataclass
class PermissionRequest:
    id: str
    tool: str
    detail: str
    created: float
    last_seen: float
    status: str = "pending"  # pending | allow | deny
    decided_at: float = field(default=0.0)


class PermissionQueue:
    """同意/否决请求的排队。

    安全约定：**只有 `decide()` 能产生 allow/deny，它只被诗音界面上的按钮回调调用**；
    HTTP 服务只有 open / wait / withdraw 三个入口，没有任何一个能写入决定。
    其他所有结局（超时、撤回、过期、未知 id）一律是 "gone"，hook 对 "gone" 不给决定。
    """

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._items: dict[str, PermissionRequest] = {}

    # ---- 给 HTTP 服务线程 ----
    def open(self, tool: str, detail: str, now: Optional[float] = None) -> Optional[str]:
        """登记一个请求，返回 id；排队已满返回 None。"""
        now = time.monotonic() if now is None else now
        with self._cond:
            pending = sum(1 for r in self._items.values() if r.status == "pending")
            if pending >= MAX_PENDING:
                return None
            rid = secrets.token_hex(16)
            self._items[rid] = PermissionRequest(
                rid, str(tool)[:TOOL_MAX], str(detail)[:DETAIL_MAX], now, now
            )
            self._cond.notify_all()
            return rid

    def wait(self, rid: str, seconds: float, now: Optional[float] = None) -> str:
        """等这个请求有结果，最多 seconds 秒。返回 pending / allow / deny / gone。
        拿到 allow/deny 后请求即被取走（只能取一次）。"""
        seconds = max(0.0, min(float(seconds), MAX_WAIT))
        deadline = time.monotonic() + seconds
        with self._cond:
            while True:
                item = self._items.get(rid)
                if item is None:
                    return "gone"
                item.last_seen = time.monotonic() if now is None else now
                if item.status != "pending":
                    del self._items[rid]
                    return item.status
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return "pending"
                self._cond.wait(remaining)

    def withdraw(self, rid: str) -> None:
        """hook 不再等了（超时）：撤掉请求。不产生任何决定。"""
        with self._cond:
            self._items.pop(rid, None)
            self._cond.notify_all()

    # ---- 给 GUI 线程 ----
    def decide(self, rid: str, allow: bool) -> bool:
        """用户在诗音上点了按钮。只对仍在等待的请求有效。"""
        with self._cond:
            item = self._items.get(rid)
            if item is None or item.status != "pending":
                return False
            item.status = "allow" if allow else "deny"
            item.decided_at = time.monotonic()
            self._cond.notify_all()
            return True

    def pending(self) -> list[PermissionRequest]:
        """还在等用户决定的请求，按到达顺序。"""
        with self._cond:
            return [r for r in self._items.values() if r.status == "pending"]

    def expire(self, now: Optional[float] = None) -> list[str]:
        """清掉没人轮询的请求（hook 已经被 CC 杀掉）和没人来取的决定。返回被清掉的 id。"""
        now = time.monotonic() if now is None else now
        with self._cond:
            dead = [
                r.id for r in self._items.values()
                if (r.status == "pending" and now - r.last_seen > PENDING_IDLE)
                or (r.status != "pending" and now - r.decided_at > DECIDED_KEEP)
            ]
            for rid in dead:
                del self._items[rid]
            if dead:
                self._cond.notify_all()
            return dead
