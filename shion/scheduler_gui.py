"""Presentation adapter. No execution controls, identity guessing or disk I/O.

The legacy Claude protocol has no turn ID: its live state/request queue are
display supplements only. Fully identified observations use the existing ledger.
"""
import logging

from .events import ObserverHeartbeat
from .scheduler import Display, Priority, Scheduler

log = logging.getLogger("shion.scheduler_gui")


class SchedulerGUI:
    def __init__(self, clock, enabled=False):
        self.core = Scheduler(enabled=enabled, clock=clock)
        self.display = None
        self._announced = set()
        self._shown_since = clock()

    def attach(self, connection):
        if connection.presentation is self.core and connection.ledger is self.core.ledger:
            return True
        # The connection remains the owner of the single lifecycle ledger.
        # Attach before consuming any GUI observations; no state reconstruction.
        if self.core.ledger.tasks and self.core.ledger is not connection.ledger:
            log.warning("Cannot attach observation connection after GUI events; disabling v2 presentation")
            self.set_enabled(False)
            return False
        self.core.ledger = connection.ledger
        connection.presentation = self.core
        return True

    def set_enabled(self, enabled):
        if self.core.enabled == enabled:
            return
        self.core.observation_gap(paused=True)
        self.core.notices.clear()
        self.core.coverage_known = False
        self.core._maintain()
        self.core._foreground = None
        self.core._current = None
        self.core.enabled = enabled
        self.display = None
        # Dedup tombstones stay in the ledger; switching cannot revive work.

    def observe(self, event):
        if isinstance(event, ObserverHeartbeat):
            self.core.heartbeat(event)
        else:
            self.core.observe(event)

    def refresh(self, *, claude_working=False, permissions=()):
        previous = self.display
        if (previous and previous.priority == Priority.P3 and previous.token is not None
                and self.core.clock() - self._shown_since >= 3.0):
            self.core.acknowledge(previous)
        extras = [Display(Priority.P1, "waiting_user_confirmed", "Claude", request_id=p.id)
                  for p in permissions]
        if claude_working:
            extras.append(Display(Priority.P4, "observed_working", "Claude"))
        self.display = self.core.select(extras)
        if self.display != previous:
            self._shown_since = self.core.clock()
        return self.display

    def text(self, ui):
        d = self.display
        if d is None:
            return ""
        return ui("v2_status", brand=d.brand or ui("v2_all"), state=ui("v2_" + d.state))

    def pending_chatgpt(self):
        return self.core.enabled and any(k[0] == "chatgpt" and not t.terminal and
            (t.permission_unknown or t.state == "waiting_user_confirmed")
            for k, t in self.core.ledger.tasks.items())

    def notice(self):
        d = self.display
        if d is None or d.priority > Priority.P3 or not d.tasks:
            return False
        identity = ("notice", d.token) if d.token is not None else (d.priority, d.state, d.tasks, d.request_id)
        if identity in self._announced:
            return False
        # Bounded by task/notice capacity; don't drop old identities and re-alert.
        if len(self._announced) >= 4096:
            return False
        self._announced.add(identity)
        return True

    def sprite(self, current, *, protected=False):
        d = self.display
        if d is None or protected:
            return current
        if d.priority == Priority.P1:
            return "stop"
        if d.priority == Priority.P2:
            return "stop" if d.state in ("disconnected", "failed_confirmed") else "idle"
        if d.priority == Priority.P3:
            return "stop" if d.state == "interrupted" else "idle"  # Neutral end.
        if d.priority == Priority.P4:
            return "working" if current in ("idle", "working", "sleep", "bed", "desk", "neglect1", "neglect2", "slump", "collapse") else current
        return current
