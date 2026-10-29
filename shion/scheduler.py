"""Opt-in, metadata-only Phase 2 core. No GUI, filesystem, network or controls.

Adapters must establish capabilities and verified foreground identity. The
production controller deliberately does not import or instantiate this module.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
from enum import IntEnum
import time

from .events import ID, Observation, ObserverHeartbeat
from .tasks import TaskLedger

TaskKey = tuple[str, str, str, str]


class Priority(IntEnum):
    P1 = 1  # Confirmed human action, with an independent request ID.
    P2 = 2  # Confirmed final failure, connection loss or uncertainty.
    P3 = 3  # Neutral turn end / interruption.
    P4 = 4  # Observed work.
    P5 = 5  # Known idle only.


@dataclass(frozen=True)
class SourceCapabilities:
    human_wait: bool = False
    request_resolution: bool = False
    final_failure: bool = False


@dataclass
class RequestRecord:
    status: str  # open / resolved / unknown
    last: float


@dataclass(frozen=True)
class Display:
    priority: Priority
    state: str
    brand: str = ""
    tasks: tuple[TaskKey, ...] = ()
    request_id: str = ""
    result: str = "unknown"
    token: int | None = None


@dataclass
class Notice:
    display: Display
    created: float


class Scheduler:
    def __init__(self, *, enabled=False, clock=time.monotonic, capabilities=None,
                 capacity=1024, notice_capacity=128, merge_window=2.0,
                 notice_ttl=30.0, min_display=1.0, rotation=5.0, foreground_delay=0.3):
        self.enabled, self.clock = enabled, clock
        self.ledger = TaskLedger(clock=clock, capacity=capacity)
        # Keyed by provider, runtime namespace, channel and client surface.
        self.capabilities = dict(capabilities or {})
        self.requests: dict[tuple[TaskKey, str], RequestRecord] = {}
        self.notices: OrderedDict[int, Notice] = OrderedDict()
        self.capacity, self.notice_capacity = capacity, notice_capacity
        self.merge_window, self.notice_ttl = merge_window, notice_ttl
        self.min_display, self.rotation = min_display, rotation
        self.foreground_delay = foreground_delay
        self.coverage_known = False
        self.degraded = False
        self._serial = 0
        self._current = None
        self._shown_at = 0.0
        self._foreground = None
        self._foreground_since = 0.0

    @staticmethod
    def brand(provider):
        return {"claude": "Claude", "chatgpt": "ChatGPT"}[provider]

    def _caps(self, event):
        return self.capabilities.get((event.provider, event.namespace, event.source, event.client_surface),
                                     SourceCapabilities())

    def observe(self, event: Observation):
        if not self.enabled:
            return
        if event.provider not in ("claude", "chatgpt"):
            raise ValueError("unknown provider")
        result = self.ledger.accept(event)
        if result:
            self._queue(result, Priority.P3, event.key)
        self._maintain()

    def heartbeat(self, event: ObserverHeartbeat):
        if self.enabled:
            self.ledger.heartbeat(event)
            self._maintain()

    def _request_slot(self, key, request_id):
        if not isinstance(request_id, str) or not ID.fullmatch(request_id):
            return False
        if (key, request_id) not in self.requests and len(self.requests) >= self.capacity:
            self.degraded = True
            return False
        return True

    def open_request(self, event: Observation, request_id: str):
        """Observe reliable human-wait evidence; never authorize a request."""
        if not self.enabled:
            return
        if event.event != "PermissionRequest":
            raise ValueError("human wait requires request evidence")
        if (self._caps(event).human_wait and isinstance(request_id, str) and ID.fullmatch(request_id)
                and (event.key, request_id) in self.requests):
            return  # Request dedup is separate from lifecycle dedup, including resolved tombstones.
        previous = self.ledger.tasks.get(event.key)
        prior_unknown = previous.permission_unknown if previous else False
        self.observe(event)
        task = self.ledger.tasks.get(event.key)
        if task is None or task.terminal:
            return
        if not self._caps(event).human_wait or not self._request_slot(event.key, request_id):
            task.permission_unknown = True
            return
        identity = event.key, request_id
        # Resolution/unknown tombstones cannot be reopened by delayed duplicates.
        if identity not in self.requests:
            self.requests[identity] = RequestRecord("open", self.clock())
            task.permission_unknown = prior_unknown
            task.state = "waiting_user_confirmed"
            task.continuity_lost = False

    def resolve_request(self, event: Observation, request_id: str):
        """Consume resolution metadata only; does not send a control command."""
        if not self.enabled or not self._caps(event).request_resolution:
            return
        if not self._request_slot(event.key, request_id):
            self.degraded = True
            return
        self.requests[event.key, request_id] = RequestRecord("resolved", self.clock())
        task = self.ledger.tasks.get(event.key)
        if task and not task.terminal and task.state == "waiting_user_confirmed":
            if not any(k == event.key and r.status == "open" for (k, _), r in self.requests.items()):
                # An answer is not proof that work has resumed.
                task.state = "uncertain"

    def final_failure(self, event: Observation):
        if not self.enabled or not self._caps(event).final_failure:
            return
        task = self.ledger.tasks.get(event.key)
        if task and task.terminal:
            return
        result = self.ledger.accept(replace(event, event="Stop"))
        if result:
            task = self.ledger.tasks[event.key]
            task.state, task.result = "failed_confirmed", "failed"
            self._queue("failed_confirmed", Priority.P2, event.key)
        self._maintain()

    def confirm_coverage(self):
        """For a future verified snapshot adapter, never inferred from silence."""
        if self.enabled:
            self.coverage_known = True

    def set_foreground(self, key: TaskKey | None, *, verified=False):
        if self.enabled and verified and key != self._foreground:
            self._foreground, self._foreground_since = key, self.clock()

    def _queue(self, state, priority, key):
        now = self.clock()
        brand = self.brand(key[0])
        for notice in reversed(self.notices.values()):
            d = notice.display
            if d.state == state and d.brand == brand and now - notice.created <= self.merge_window:
                if key not in d.tasks:
                    if len(d.tasks) >= self.capacity:
                        self.degraded = True
                        return
                    notice.display = replace(d, tasks=d.tasks + (key,))
                return
        if len(self.notices) >= self.notice_capacity:
            self.degraded = True  # Visible P2; never silently claim idle.
            return
        self._serial += 1
        self.notices[self._serial] = Notice(Display(priority, state, brand, (key,),
            result="failed" if state == "failed_confirmed" else "unknown", token=self._serial), now)

    def _maintain(self):
        self.ledger.expire()
        for (key, _), request in self.requests.items():
            task = self.ledger.tasks.get(key)
            if request.status == "open" and (task is None or task.terminal or task.continuity_lost
                                             or task.state in ("uncertain", "disconnected")):
                request.status = "unknown"
                if task and not task.terminal:
                    task.permission_unknown = True
        for token, notice in list(self.notices.items()):
            if self.clock() - notice.created >= self.notice_ttl:
                del self.notices[token]

    @property
    def pending_requests(self):
        self._maintain()
        return tuple(identity for identity, request in self.requests.items() if request.status == "open")

    def candidates(self):
        if not self.enabled:
            return []
        self._maintain()
        out = [Display(Priority.P1, "waiting_user_confirmed", self.brand(key[0]), (key,), request_id)
               for key, request_id in self.pending_requests]
        # Connection faults merge by connection identity, retaining every affected task.
        faults = OrderedDict()
        for key, task in self.ledger.tasks.items():
            if task.terminal:
                continue
            if task.state in ("uncertain", "disconnected") or task.conflict or task.permission_unknown:
                state = task.state if task.state in ("uncertain", "disconnected") else "uncertain"
                identity = key[:2], tuple(sorted(task.observers)), state
                faults.setdefault(identity, []).append(key)
            elif task.state == "observed_working":
                out.append(Display(Priority.P4, task.state, self.brand(key[0]), (key,)))
        out += [Display(Priority.P2, identity[-1], self.brand(keys[0][0]), tuple(keys))
                for identity, keys in faults.items()]
        if self.degraded or self.ledger.uncertain:
            out.append(Display(Priority.P2, "uncertain"))
        out += [notice.display for notice in self.notices.values()]
        if not out:
            out.append(Display(Priority.P5 if self.coverage_known else Priority.P2,
                               "idle" if self.coverage_known else "uncertain"))
        return out

    @staticmethod
    def _identity(display):
        return display.priority, display.state, display.tasks, display.request_id, display.token

    def select(self):
        candidates = self.candidates()
        if not candidates:
            return None
        priority = min(d.priority for d in candidates)
        choices = [d for d in candidates if d.priority == priority]
        current = next((d for d in choices if self._current and
                        self._identity(d) == self._identity(self._current)), None)
        now = self.clock()
        if current and now - self._shown_at < self.min_display:
            return current
        foreground = next((d for d in choices if self._foreground in d.tasks), None)
        if foreground and now - self._foreground_since >= self.foreground_delay:
            chosen = foreground
        elif current and now - self._shown_at < self.rotation:
            return current
        elif current:
            chosen = choices[(choices.index(current) + 1) % len(choices)]
        else:
            chosen = choices[0]
        if not current or self._identity(chosen) != self._identity(current):
            self._shown_at = now
        elif now - self._shown_at >= self.rotation:
            self._shown_at = now
        self._current = chosen
        return chosen

    def acknowledge(self, display: Display):
        """Dismiss a neutral reminder; P1 remains until actual resolution evidence."""
        if display.token is not None:
            self.notices.pop(display.token, None)
