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
HOLD_GRACE = 2.0  # hook 两段长轮询之间的空当，这么久之内仍算“在等”


class RemoteHub:
    """停下 / 继续 / 结束这一轮 / 立即中断，都可以按会话进行。

    暂停有两层：全局（菜单“全部”，以及只有 0～1 个会话时的原有行为）和单个会话。
    会话 s 要等 = s 被单独停下，或全局停下中且 s 没有被单独放行。没有 session 的旧请求只看全局。
    """

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._paused = False  # 全局暂停
        self._paused_sessions: set[str] = set()  # 被单独停下的会话
        self._exempt: set[str] = set()  # 全局暂停中被单独放行的会话（继续 / 在 CC 里说话 / 结束这一轮）
        self._end_gen = 0  # 全局“结束这一轮”的一次性代数
        self._end_gens: dict[str, int] = {}  # 按会话的“结束这一轮”代数
        self._holding = 0  # 正在检查点等待的 hook 总数
        self._last_hold = float("-inf")
        self._held: dict[Optional[str], int] = {}  # 会话 → 正在等的 hook 数（None = 没带 session 的旧请求）
        self._held_last: dict[Optional[str], float] = {}  # 会话 → 最近一次退出等待的时刻
        self._held_order: dict[Optional[str], int] = {}  # 会话 → 开始等的先后（面板排序用）
        self._held_seq = 0
        self._interrupts: set[str] = set()  # 被“立即中断”的会话：下一个检查点结束这一轮（一次性）
        self._link = True  # 临时关闭联动时为 False：诗音表现得像没开
        self.permissions = PermissionQueue()

    # ---- 临时关闭联动 ----
    @property
    def link_enabled(self) -> bool:
        with self._cond:
            return self._link

    def set_link_enabled(self, enabled: bool) -> None:
        """只由诗音界面调用。关闭：所有授权请求撤回（包括已有决定还没被取走的），hook 只能拿到 gone；
        清掉暂停和中断，正在检查点等待的 hook 放行（不带停下）。开启：从空白开始，不恢复任何东西。"""
        enabled = bool(enabled)
        if not enabled:
            self.permissions.close()  # 先关授权：切换期间不可能有决定被取走
        with self._cond:
            self._link = enabled
            if not enabled:
                self._clear_pauses()
                self._interrupts.clear()
            self._cond.notify_all()
        if enabled:
            self.permissions.reopen()

    # ---- 暂停 / 继续 ----
    def _clear_pauses(self) -> None:
        self._paused = False
        self._paused_sessions.clear()
        self._exempt.clear()

    def _paused_for(self, session: Optional[str]) -> bool:
        if session is None:
            return self._paused
        return session in self._paused_sessions or (self._paused and session not in self._exempt)

    def _release(self, session: str) -> None:
        """只放行这个会话。全局暂停中：没有别的会话被单独停下、也没有别的 hook 在等时，整个解除全局暂停
        （只有一个会话时和原来“继续 / 在 CC 里说话就解除停下”完全一样）；否则只把这个会话记为已放行。"""
        self._paused_sessions.discard(session)
        if not self._paused:
            return
        now = time.monotonic()
        others = any(k != session and self._recently_held(k, now) for k in self._held)
        if not self._paused_sessions and not others:
            self._clear_pauses()
        else:
            self._exempt.add(session)

    @property
    def is_paused(self) -> bool:
        """有任何暂停（全局或某个会话）。"""
        with self._cond:
            return self._paused or bool(self._paused_sessions)

    @property
    def is_global_paused(self) -> bool:
        with self._cond:
            return self._paused

    def is_session_paused(self, session: str) -> bool:
        with self._cond:
            return self._paused_for(session)

    def paused_sessions(self) -> set[str]:
        """被单独停下的会话（不含只因全局暂停而停的）。"""
        with self._cond:
            return set(self._paused_sessions)

    def pause(self, session: Optional[str] = None) -> None:
        """None：全局停下（原行为，之后才开始工作的会话也会停）。给了会话：只停这个会话。"""
        with self._cond:
            if session is None:
                self._paused = True
                self._exempt.clear()
            else:
                self._paused_sessions.add(session)
                self._exempt.discard(session)
            self._cond.notify_all()

    def resume(self, session: Optional[str] = None) -> None:
        """None：解除全部暂停（原行为）。给了会话：只放行这个会话，其他会话的暂停不变。"""
        with self._cond:
            if session is None:
                self._clear_pauses()
            else:
                self._release(session)
            self._cond.notify_all()

    def wait_while_paused(self, seconds: float) -> bool:
        """最多等 seconds 秒，直到不再（全局）暂停。返回结束时是否仍在暂停。"""
        seconds = max(0.0, min(float(seconds), MAX_WAIT))
        with self._cond:
            self._cond.wait_for(lambda: not self._paused, timeout=seconds)
            return self._paused

    # ---- 结束这一轮 ----
    def end(self, session: Optional[str] = None) -> None:
        """None：解除全部暂停，并让此刻正在检查点等待的 hook 全部带着停下返回（原行为）。
        给了会话：只放行这个会话，只让此刻正在等的、属于这个会话的 hook 带着停下返回。
        之后才到的 hook 不受影响，不留残余状态。"""
        with self._cond:
            if session is None:
                self._clear_pauses()
                self._end_gen += 1
            else:
                self._release(session)
                self._end_gens[session] = self._end_gens.get(session, 0) + 1
            self._cond.notify_all()

    def _recently_held(self, key: Optional[str], now: float) -> bool:
        return self._held.get(key, 0) > 0 or now - self._held_last.get(key, float("-inf")) < HOLD_GRACE

    @property
    def is_holding(self) -> bool:
        """有 hook 正在检查点等待（刚退出 HOLD_GRACE 秒内也算，长轮询两段之间有空当）。"""
        with self._cond:
            return self._holding > 0 or time.monotonic() - self._last_hold < HOLD_GRACE

    def is_session_holding(self, session: str) -> bool:
        with self._cond:
            return self._recently_held(session, time.monotonic())

    def holding_sessions(self) -> list[str]:
        """正在检查点等着、而且仍在暂停的会话（宽限期内也算），按开始等的先后。没带 session 的旧请求不列出。"""
        now = time.monotonic()
        with self._cond:
            keys = [k for k in self._held if k is not None and self._recently_held(k, now) and self._paused_for(k)]
            return sorted(keys, key=lambda k: self._held_order.get(k, 0))

    # ---- 立即中断 ----
    def request_interrupt(self, sessions) -> None:
        """只由诗音界面上的“立即中断”调用：这些会话的下一个检查点返回 stop。"""
        with self._cond:
            self._interrupts.update(s for s in sessions if isinstance(s, str))
            self._cond.notify_all()

    def clear_interrupt(self, session: str) -> None:
        """这个会话的这一轮已经结束（Stop）或用户又说话了（prompt）：没用上的中断作废。"""
        with self._cond:
            self._interrupts.discard(session)

    def interrupt_pending(self, session: str) -> bool:
        with self._cond:
            return session in self._interrupts

    def wait_gate(self, seconds: float, session: Optional[str] = None) -> tuple[bool, bool]:
        """检查点：最多等 seconds 秒，直到这个会话不再暂停。返回 (仍在暂停, 这次要停下)。

        等待期间被“结束这一轮”（全局，或针对这个会话），返回 stop=True（此刻并行等待的同范围 hook 都会拿到）；
        这个会话被“立即中断”过，立即返回 stop=True（只生效一次）。
        """
        seconds = max(0.0, min(float(seconds), MAX_WAIT))
        with self._cond:
            if not self._link:
                return False, False  # 临时关闭联动：不停、不中断
            if session is not None and session in self._interrupts:
                self._interrupts.discard(session)
                return False, True
            if not self._paused_for(session):
                return False, False
            gen = self._end_gen
            sgen = self._end_gens.get(session, 0) if session is not None else 0

            def ended() -> bool:
                return self._end_gen != gen or (session is not None and self._end_gens.get(session, 0) != sgen)

            now = time.monotonic()
            if not self._recently_held(session, now):
                self._held_seq += 1
                self._held_order[session] = self._held_seq
            self._holding += 1
            self._held[session] = self._held.get(session, 0) + 1
            try:
                self._cond.wait_for(
                    lambda: not self._paused_for(session) or ended() or not self._link
                    or (session is not None and session in self._interrupts),
                    timeout=seconds)
            finally:
                self._holding -= 1
                self._held[session] -= 1
                self._last_hold = self._held_last[session] = time.monotonic()
            if not self._link:
                return False, False  # 等待中被临时关闭：放行
            if session is not None and session in self._interrupts:
                self._interrupts.discard(session)
                return self._paused_for(session), True
            return self._paused_for(session), ended()


# ---------------------------------------------------------------- 授权请求
MAX_PENDING = 20  # 同时排队的授权请求上限，防止被灌满
DETAIL_MAX = 20000  # 命令/路径/计划全文的字数上限
TOOL_MAX = 60
PENDING_IDLE = 25.0  # 请求超过这么久没被 hook 轮询，就认为 hook 已经没了（用户在 CC 里自己答了）
DECIDED_KEEP = 60.0  # 已有决定但没人来取的请求，保留多久
DISABLED = "disabled"  # open() 在临时关闭联动时的返回值（不是 id：真正的 id 是 32 位十六进制）


@dataclass
class PermissionRequest:
    id: str
    tool: str
    detail: str
    created: float
    last_seen: float
    status: str = "pending"  # pending | allow | deny
    decided_at: float = field(default=0.0)
    session: str = ""  # 来自哪个 CC 会话（旧 hook 没有）
    key: str = ""  # 工具名 + 参数的指纹，和 PostToolUse 配对


class PermissionQueue:
    """同意/否决请求的排队。

    安全约定：**只有 `decide()` 能产生 allow/deny，它只被诗音界面上的按钮回调调用**；
    HTTP 服务只有 open / wait / withdraw / settle 四个入口，没有任何一个能写入决定。
    其他所有结局（超时、撤回、过期、未知 id）一律是 "gone"，hook 对 "gone" 不给决定。
    """

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._items: dict[str, PermissionRequest] = {}
        self._closed = False  # 临时关闭联动：不登记、不等、不产生决定

    # ---- 临时关闭联动（只由 RemoteHub.set_link_enabled 调用）----
    def close(self) -> None:
        """撤回全部请求，包括已有决定还没被取走的：正在长轮询的 hook 醒来只能拿到 gone。"""
        with self._cond:
            self._closed = True
            self._items.clear()
            self._cond.notify_all()

    def reopen(self) -> None:
        with self._cond:
            self._closed = False

    @property
    def closed(self) -> bool:
        with self._cond:
            return self._closed

    # ---- 给 HTTP 服务线程 ----
    def open(self, tool: str, detail: str, now: Optional[float] = None,
             session: str = "", key: str = "") -> Optional[str]:
        """登记一个请求，返回 id；排队已满返回 None；临时关闭联动时返回 DISABLED。"""
        now = time.monotonic() if now is None else now
        with self._cond:
            if self._closed:
                return DISABLED
            pending = sum(1 for r in self._items.values() if r.status == "pending")
            if pending >= MAX_PENDING:
                return None
            rid = secrets.token_hex(16)
            self._items[rid] = PermissionRequest(
                rid, str(tool)[:TOOL_MAX], str(detail)[:DETAIL_MAX], now, now,
                session=session, key=key,
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
                if item is None or self._closed:
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

    def settle(self, session: str, key: Optional[str] = None) -> int:
        """这个会话的授权已经在 CC 里答过了（工具跑完 / 这一轮结束 / 用户又说话）：撤掉它还在等的请求。
        给了 key 就只撤指纹相同的。只会删除，不产生任何决定；hook 再来轮询得到 gone。返回撤掉几个。"""
        if not session:
            return 0
        with self._cond:
            dead = [
                r.id for r in self._items.values()
                if r.status == "pending" and r.session == session and (key is None or r.key == key)
            ]
            for rid in dead:
                del self._items[rid]
            if dead:
                self._cond.notify_all()
            return len(dead)

    # ---- 给 GUI 线程 ----
    def decide(self, rid: str, allow: bool) -> bool:
        """用户在诗音上点了按钮。只对仍在等待的请求有效。"""
        with self._cond:
            item = self._items.get(rid)
            if self._closed or item is None or item.status != "pending":
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
