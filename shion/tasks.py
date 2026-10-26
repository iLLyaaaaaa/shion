"""Bounded read-only lifecycle ledger; terminal never means successful."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import time

from .events import Observation


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


class TaskLedger:
    def __init__(self, clock=time.monotonic, capacity=1024, ttl=300):
        self.clock, self.capacity, self.ttl = clock, capacity, ttl
        self.tasks = OrderedDict()
        self.uncertain = False
        self.received = 0
        self.duplicates = 0

    def accept(self, event: Observation):
        self.received += 1
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
        task.last = now
        if event.event in ("Stop", "Interrupt"):
            task.state = "interrupted" if event.event == "Interrupt" else "turn_ended"
            task.terminal = True
            task.tools.clear()
            return task.state
        if event.event in ("UserPromptSubmit", "PreToolUse"):
            task.state = "observed_working"
            if event.tool_use_id:
                task.tools.add(event.tool_use_id)
        elif event.event == "PostToolUse":
            task.tools.discard(event.tool_use_id)
            # A tool result is evidence of activity, never of final success.
            task.state = "observed_working"
        elif event.event == "PermissionRequest":
            task.permission_unknown = True
            task.state = "uncertain"
        return None

    def expire(self):
        for task in self.tasks.values():
            if not task.terminal and self.clock() - task.last >= self.ttl:
                task.state = "uncertain"

    def disconnect(self):
        self.uncertain = True
        for task in self.tasks.values():
            if not task.terminal:
                task.state = "disconnected"

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
