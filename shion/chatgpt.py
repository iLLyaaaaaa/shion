"""Read-only ChatGPT observation and review-first global connection management."""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

from .observer import ObservationServer, credentials
from .tasks import TaskLedger
from .events import ObserverHeartbeat
from . import observer_files as secure
from tools import codex_config as config

log = logging.getLogger("shion.chatgpt")

# 菜单/状态里“待确认、已断开”最多显示这么久（秒，两倍于任务过期时间）。只是不再显示，
# 不推断旧任务成功；调度器用的仍是 ledger 原来的粘滞标志。
UNKNOWN_WINDOW = 600.0


def log_observation(event):
    """Only validated metadata; logging failure must not interrupt observation."""
    try:
        log.info("观察事件：%s session=%s turn=%s", event.event,
                 event.session_id[:8], event.turn_id[:8])
    except Exception:
        pass


def observer_command():
    if getattr(sys, "frozen", False):
        return [sys.executable, "--codex-observer"]
    # Absolute bootstrap path works in every project without PYTHONPATH changes.
    root = Path(__file__).resolve().parent.parent
    return [sys.executable, "-B", str(root / "hooks" / "codex_observer.py")]


class ChatGPTConnection:
    def __init__(self, directory, home=None):
        self.directory = Path(directory)
        self.private_directory = self.directory
        self.home = home or config.codex_home()
        self.ledger = TaskLedger()
        self.presentation = None  # Optional GUI scheduler; shares this ledger.
        self.server = None
        self.error = False
        self.enabled = True
        self._last_notice = 0.0
        # 启动前可能已有没看到开头的任务：启动后 ledger.ttl 秒内显示“待确认”（那之后这类任务也已过期）
        self._unobserved_start = True
        self._started_at = self.ledger.clock()
        self._disconnected_keys = set()
        self._disconnect_notice_pending = False

    def start(self):
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            secret = credentials(self.private_directory)
            self.enabled = secret["enabled"]
            self.server = ObservationServer(secret["token"], secret["port"])
            self.server.inbox.enabled = self.enabled
            self.server.start()
        except (OSError, ValueError):
            self.error = True

    def stop(self):
        if self.server:
            self.server.stop()
            self.server = None

    def toggle(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        secret = credentials(self.private_directory)
        secret["enabled"] = not self.enabled
        secure.replace_private(self.private_directory / "chatgpt-observer.json", json.dumps(secret).encode("utf-8"))
        self.enabled = secret["enabled"]
        if self.server:
            self.server.inbox.enabled = self.enabled
            self.server.inbox.drain()
        # Keep dedup tombstones across disable/enable; no Claude mutations.
        if self.presentation is not None and self.presentation.enabled:
            self.presentation.observation_gap(provider="chatgpt", paused=True)
        else:
            self.ledger.disconnect(provider="chatgpt")

    @property
    def working(self):
        self.ledger.expire()
        return sum(t.state == "observed_working" for k, t in self.ledger.tasks.items() if k[0] == "chatgpt")

    def poll(self):
        notices = []
        if self.server:
            core = self.presentation if self.presentation is not None and self.presentation.enabled else None
            # Consume a degradation once, before processing later evidence. A
            # second loss during drain stays flagged for the next poll.
            gap = bool(core and self.server.inbox.degraded.is_set())
            if gap:
                self.server.inbox.degraded.clear()
            events = self.server.inbox.drain()
            if core and (gap or self.server.inbox.degraded.is_set()):
                core.observation_gap(provider="chatgpt", paused=not self.enabled)
                events = []  # Batch order relative to the missing packets is unknown.
            for event in events:
                if isinstance(event, ObserverHeartbeat):
                    if self.enabled:
                        (core or self.ledger).heartbeat(event)
                    continue
                log_observation(event)
                if self.enabled:
                    if self.presentation is not None and self.presentation.enabled:
                        self.presentation.observe(event)
                        result = None
                    else:
                        result = self.ledger.accept(event)
                    if result:
                        notices.append(result)
            if core is None and self.server.inbox.degraded.is_set():
                # 一次降级只算一次：标记当时的任务为断开，然后清掉，之后的新任务不受牵连
                self.server.inbox.degraded.clear()
                self.ledger.disconnect(provider="chatgpt")
        self.ledger.expire()
        lost = {key for key, task in self.ledger.tasks.items()
                if self.enabled and key[0] == "chatgpt" and task.state == "disconnected"}
        if not lost:
            self._disconnect_notice_pending = False
        self._disconnect_notice_pending |= bool(lost - self._disconnected_keys)
        self._disconnected_keys = lost
        # Bounded neutral reminders; no success actions or affection path.
        if self._disconnect_notice_pending and time.monotonic() - self._last_notice >= 2:
            self._disconnect_notice_pending = False
            self._last_notice = time.monotonic()
            return "chatgpt_disconnected_say"  # 气泡用诗音口吻；菜单状态仍用 chatgpt_disconnected
        if notices and time.monotonic() - self._last_notice >= 2:
            self._last_notice = time.monotonic()
            return "chatgpt_interrupted" if "interrupted" in notices else "chatgpt_ended"
        return None

    def _shown_lost(self, tasks) -> bool:
        """最近 UNKNOWN_WINDOW 秒内有过动静、现在断开的任务（更早的不再显示为断开）。"""
        now = self.ledger.clock()
        return any(t.state == "disconnected" and now - t.last < UNKNOWN_WINDOW for t in tasks)

    def _shown_unknown(self, tasks) -> bool:
        """是否显示“待确认”。只看最近的不确定：全局标志、不确定任务都有时效，启动时的“没看到开头”只算 ttl 秒。"""
        now = self.ledger.clock()
        at = self.ledger.uncertain_at
        return bool(
            self.error
            or (self.ledger.uncertain and at is not None and now - at < UNKNOWN_WINDOW)
            or any(t.state == "uncertain" and now - t.last < UNKNOWN_WINDOW for t in tasks)
            or (self._unobserved_start and now - self._started_at < self.ledger.ttl))

    def status(self, ui):
        if not self.enabled:
            return ui("chatgpt_disabled")
        tasks = [t for k, t in self.ledger.tasks.items() if k[0] == "chatgpt"]
        text = ui("chatgpt_status", count=self.working, received=self.ledger.received_by_provider.get("chatgpt", 0)) + "\n" + ui(
            "chatgpt_disconnected" if self._shown_lost(tasks) else
            "chatgpt_uncertain" if self._shown_unknown(tasks) else "chatgpt_observation")
        if any(t.permission_unknown and not t.terminal for t in tasks):
            text += "\n" + ui("chatgpt_permission_unknown")
        return text

    def connection_state(self):
        """菜单“连接”行：off / installed / not_installed / error。只读 Shion 自己的安装记录，不解析 Codex 配置。"""
        if not self.enabled:
            return "off"
        try:
            return "installed" if config.read_ownership(self.home, self.private_directory) is not None else "not_installed"
        except Exception:  # 读不了或旧版记录冲突：只是显示，不能让菜单打不开
            return "error"

    def activity(self, ui):
        """菜单“活动”行：(文字, tooltip 或 None)。关闭或未安装时没有活动，显示“—”。"""
        if not self.enabled or self.connection_state() == "not_installed":
            return ui("activity_link_none"), None
        tasks = [t for k, t in self.ledger.tasks.items() if k[0] == "chatgpt"]
        rounds = ui("activity_link_rounds", count=self.working)
        if self._shown_lost(tasks):
            return ui("activity_link_unknown", rounds=rounds), ui("link_lost_hint")
        if self._shown_unknown(tasks):
            return ui("activity_link_unknown", rounds=rounds), ui("link_unknown_hint")
        return rounds, None

    def plan(self, uninstall=False):
        return config.uninstall_plan(self.home, self.private_directory) if uninstall else config.install_plan(
            self.home, observer_command(), self.private_directory, self.private_directory)


def review_connection(controller, uninstall=False):
    """Concrete diff before any user configuration write. Trust remains in Codex."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox
    from .windowing import position_dialog
    ui = controller.lines.ui
    connection = controller.chatgpt
    try:
        plan = connection.plan(uninstall)
        summary = config.inspect(connection.home, connection.private_directory)
        box = QMessageBox(controller.window)
        box.setWindowTitle(ui("chatgpt_manage"))
        box.setTextFormat(Qt.PlainText)
        box.setText(ui("chatgpt_review"))
        box.setDetailedText(json.dumps(summary, ensure_ascii=False, indent=2) + "\n\n" + plan.diff())
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Cancel)
        position_dialog(box, controller.window.body_rect())
        if box.exec() == QMessageBox.Yes:
            config.apply_plan(plan)
            controller.say(ui("chatgpt_removed" if uninstall else "chatgpt_trust"))
    except (OSError, ValueError) as exc:
        controller.say(ui("chatgpt_config_error", error=str(exc)))
