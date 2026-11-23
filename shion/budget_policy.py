"""Per-session budget state shared by the checkpoint service and the GUI."""
from __future__ import annotations

from datetime import datetime, timedelta
from threading import Lock

from shion.remote import BudgetPause, RemoteHub
from shion.state import SessionBudget, valid_budget

RETENTION = timedelta(days=7)
BUDGET_TIERS = (10_000_000, 50_000_000, 100_000_000)


class BudgetPolicy:
    def __init__(self, default=None, sessions=None, *, clock=datetime.now):
        self._clock = clock
        self._lock = Lock()
        self._default = default
        self._sessions = dict(sessions or {})
        self._dirty = False
        self._sweep_at = datetime.min

    def set_default(self, value: int | None) -> None:
        if value is not None and not valid_budget(value):
            raise ValueError("budget must be a positive integer or None")
        with self._lock:
            self._default = value

    def _record(self, session, budget, now):
        self._sessions[session] = SessionBudget(budget, now)
        self._dirty = True

    def touch(self, session: str) -> None:
        """Other hook events keep existing budgets alive, even with accounting off."""
        with self._lock:
            now = self._clock()
            record = self._sessions.get(session)
            if record is not None and now - record.last_active < RETENTION:
                self._record(session, record.budget, now)

    def observe(self, session: str, total: int, hub: RemoteHub) -> bool:
        """Apply the default on the first reading and atomically request a budget hold."""
        with self._lock:
            now = self._clock()
            record = self._sessions.get(session)
            budget = record.budget if record and now - record.last_active < RETENTION else self._default
            self._record(session, budget, now)
            return budget is not None and total >= budget and hub.pause(session, budget=BudgetPause(total, budget))

    def choose(self, session: str, hold: BudgetPause, budget: int | None, hub: RemoteHub) -> bool:
        if budget is not None and (not valid_budget(budget) or budget <= hold.total):
            return False
        with self._lock:
            if not hub.resume_budget(session, hold):
                return False
            self._record(session, budget, self._clock())
            return True

    def take_changes(self) -> dict[str, SessionBudget] | None:
        """Return a detached snapshot for the GUI's existing save scheduler."""
        with self._lock:
            now = self._clock()
            if now >= self._sweep_at:
                fresh = {s: r for s, r in self._sessions.items() if now - r.last_active < RETENTION}
                self._dirty |= len(fresh) != len(self._sessions)
                self._sessions = fresh
                self._sweep_at = min((r.last_active + RETENTION for r in fresh.values()),
                                     default=now + RETENTION)
            if self._dirty:
                self._dirty = False
                return dict(self._sessions)
            return None
