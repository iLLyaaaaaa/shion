"""Bounded read-only lifecycle ledger; terminal never means successful."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import time

from .events import Observation, ObserverHeartbeat

OBSERVER_LEASE = 10.0  # Five missed 2s pulses; receiver monotonic time only.


@dataclass
class TaskRecord:
    state: str
    last: float
    sources: set[str] = field(default_factory=set)
    tools: set[str] = field(default_factory=set)
    seen: set[tuple] = field(default_factory=set)
    conflict: bool = False
    permission_unknown: bool = False
    terminal: bool = False
    result: str = "unknown"
    observers: set[str] = field(default_factory=set)
    contexts: set[tuple] = field(default_factory=set)
    lease_supported: bool = False
    continuity_lost: bool = False


@dataclass
class ObserverLease:
    last: float
    continuous_since: float


class TaskLedger:
    def __init__(self, clock=time.monotonic, capacity=1024, ttl=300, lease_ttl=OBSERVER_LEASE):
        self.clock, self.capacity, self.ttl = clock, capacity, ttl
        self.tasks = OrderedDict()
        self.uncertain = False
        self.received = 0
        self.duplicates = 0
        self.lease_ttl = lease_ttl
        self.leases: dict[str, ObserverLease] = {}

    def heartbeat(self, pulse: ObserverHeartbeat):
        self.expire()
        now = self.clock() if pulse.received_at is None else pulse.received_at
        lease = self.leases.get(pulse.observer)
        if lease is None:
            if len(self.leases) >= self.capacity:
                self.uncertain = True
                return
            self.leases[pulse.observer] = ObserverLease(now, now)
        elif now > lease.last:
            if now - lease.last >= self.lease_ttl:
                lease.continuous_since = now
            lease.last = now

    def _live(self, observer):
        lease = self.leases.get(observer)
        return lease is not None and self.clock() - lease.last < self.lease_ttl

    def accept(self, event: Observation):
        self.expire()
        self.received += 1
        # A duplicate packet can prove transport life, never task continuity.
        if event.leased:
            self.heartbeat(ObserverHeartbeat(event.observer, event.received_at))
        if event.event == "SessionStart":
            if not event.session_id:
                self.uncertain = True
            return None
        if not event.session_id or not event.turn_id:
            self.uncertain = True
            return None
        now = self.clock()
        task = self.tasks.get(event.key)
        if task is None:
            # Do not evict terminal tombstones and revive delayed old events.
            if len(self.tasks) >= self.capacity:
                self.uncertain = True
                return None
            task = TaskRecord("uncertain", now)
            self.tasks[event.key] = task
        task.sources.add(event.source)
        context = event.provider, event.namespace, event.client_surface, event.source, event.observer
        if context not in task.contexts and len(task.contexts) >= 32:
            self.uncertain = True
            task.state = "uncertain"
            return None
        task.contexts.add(context)
        task.conflict |= len(task.sources) > 1
        if task.conflict:
            self.uncertain = True
        identity = (event.event, event.tool_use_id)
        dedupable = event.event in ("Stop", "Interrupt", "UserPromptSubmit") or bool(event.tool_use_id)
        if dedupable and identity in task.seen:
            self.duplicates += 1
            return None
        if task.terminal:
            if event.event == "Interrupt":
                task.state = "interrupted"
            return None
        if dedupable:
            if len(task.seen) >= 2048:
                self.uncertain = True
                task.state = "uncertain"
                return None
            task.seen.add(identity)
        task.last = now if event.received_at is None else event.received_at
        if event.leased:
            task.observers.add(event.observer)
            task.lease_supported = True
        if event.event in ("Stop", "Interrupt"):
            task.state = "interrupted" if event.event == "Interrupt" else "turn_ended"
            task.terminal = True
            task.tools.clear()
            return task.state
        if event.event in ("UserPromptSubmit", "PreToolUse"):
            task.state = "observed_working"
            task.continuity_lost = False
            if event.tool_use_id:
                task.tools.add(event.tool_use_id)
        elif event.event == "PostToolUse":
            task.tools.discard(event.tool_use_id)
            # A tool result is evidence of activity, never of final success.
            task.state = "observed_working"
            task.continuity_lost = False
        elif event.event == "PermissionRequest":
            task.permission_unknown = True
            # Permission outcome is unknown; retain independently observed activity.
        return None

    def expire(self):
        for task in self.tasks.values():
            if task.terminal:
                continue
            if task.lease_supported:
                live = [self.leases[o] for o in task.observers if self._live(o)]
                if not live:
                    task.state = "disconnected"
                    task.continuity_lost = True
                elif task.continuity_lost or not any(lease.continuous_since <= task.last for lease in live):
                    # A pulse after a gap proves only Observer life.
                    task.state = "uncertain"
                    task.continuity_lost = True
            elif self.clock() - task.last >= self.ttl:
                task.state = "uncertain"

    def disconnect(self):
        self.uncertain = True
        for task in self.tasks.values():
            if not task.terminal:
                task.state = "disconnected"
                task.continuity_lost = True

    @property
    def disconnected(self):
        self.expire()
        return any(t.state == "disconnected" for t in self.tasks.values())

    @property
    def working(self):
        self.expire()
        return sum(t.state == "observed_working" for t in self.tasks.values())

    @property
    def pending(self):
        self.expire()
        return self.uncertain or any(t.state in ("uncertain", "disconnected") or t.conflict
                                    or (t.permission_unknown and not t.terminal)
                                    for t in self.tasks.values())
