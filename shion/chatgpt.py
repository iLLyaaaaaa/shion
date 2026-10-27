"""Read-only ChatGPT observation and review-first global connection management."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from .observer import ObservationServer, credentials
from .tasks import TaskLedger
from . import observer_files as secure
from tools import codex_config as config


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
        self.server = None
        self.error = False
        self.enabled = True
        self._last_notice = 0.0
        self._unobserved_start = True

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
        self.ledger.disconnect()

    def poll(self):
        notices = []
        if self.server:
            for event in self.server.inbox.drain():
                if self.enabled:
                    result = self.ledger.accept(event)
                    if result:
                        notices.append(result)
            if self.server.inbox.degraded.is_set():
                self.ledger.disconnect()
        self.ledger.expire()
        # Bounded neutral reminders; no success actions or affection path.
        if notices and time.monotonic() - self._last_notice >= 2:
            self._last_notice = time.monotonic()
            return "chatgpt_interrupted" if "interrupted" in notices else "chatgpt_ended"
        return None

    def status(self, ui):
        if not self.enabled:
            return ui("chatgpt_disabled")
        return ui("chatgpt_status", count=self.ledger.working, received=self.ledger.received) + "\n" + ui(
            "chatgpt_uncertain" if self.error or self.ledger.pending or self._unobserved_start else "chatgpt_observation")

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
