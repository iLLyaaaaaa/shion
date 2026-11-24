"""Per-session budget state shared by the checkpoint service and the GUI."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from threading import Lock

from shion.remote import BudgetPause, RemoteHub
from shion.state import SessionBudget, valid_budget

RETENTION = timedelta(days=7)
BUDGET_TIERS = (10_000_000, 50_000_000, 100_000_000)


def budget_number(value: int | None, lang: str) -> str:
    if value is None:
        return "—"
    scales = ((1_000_000, "M"), (1_000, "K")) if lang == "en" else (
        (100_000_000, "億" if lang == "ja" else "亿"), (10_000, "万"))
    for scale, suffix in scales:
        if value >= scale:
            return f"{Decimal(value) / scale:.1f}".removesuffix(".0") + suffix
    return str(value)


@dataclass(frozen=True)
class BudgetUsage:
    total: int | None
    budget: int | None

    @property
    def near_limit(self) -> bool:
        return self.total is not None and self.budget is not None and self.total * 5 >= self.budget * 4

    @property
    def over_limit(self) -> bool:
        return self.total is not None and self.budget is not None and self.total > self.budget


class BudgetPolicy:
    def __init__(self, default=None, sessions=None, *, clock=datetime.now):
        self._clock = clock
        self._lock = Lock()
        self._default = default
        self._sessions = dict(sessions or {})
        self._totals: dict[str, int] = {}
        self._dirty = False
        self._sweep_at = datetime.min

    def set_default(self, value: int | None) -> None:
        if value is not None and not valid_budget(value):
            raise ValueError("budget must be a positive integer or None")
        with self._lock:
            self._default = value

    def _active(self, session, now):
        record = self._sessions.get(session)
        return record if record is not None and now - record.last_active < RETENTION else None

    def _record(self, session, budget, now, previous):
        if previous is None:
            self._totals.pop(session, None)
        self._sessions[session] = SessionBudget(budget, now, previous.warned if previous else frozenset())
        self._dirty = True

    def usage(self, session: str) -> BudgetUsage:
        with self._lock:
            record = self._active(session, self._clock())
            return BudgetUsage(self._totals.get(session) if record else None,
                               record.budget if record else self._default)

    def set_session(self, session: str, budget: int | None, hub: RemoteHub) -> None:
        """Apply a menu choice immediately, updating any already-held checkpoint."""
        if not session or (budget is not None and not valid_budget(budget)):
            raise ValueError("session and valid budget required")
        with self._lock:
            now = self._clock()
            self._record(session, budget, now, self._active(session, now))
            hub.update_budget_hold(session, budget)

    def touch(self, session: str) -> None:
        """Other hook events keep existing budgets alive, even with accounting off."""
        with self._lock:
            now = self._clock()
            record = self._active(session, now)
            if record is not None:
                self._record(session, record.budget, now, record)

    def observe(self, session: str, total: int, hub: RemoteHub) -> bool:
        """Apply the default on the first reading and atomically request a budget hold."""
        with self._lock:
            now = self._clock()
            record = self._active(session, now)
            budget = record.budget if record else self._default
            self._record(session, budget, now, record)
            self._totals[session] = total
            return budget is not None and total >= budget and hub.pause(session, budget=BudgetPause(total, budget))

    def choose(self, session: str, hold: BudgetPause, budget: int | None, hub: RemoteHub) -> bool:
        if budget is not None and (not valid_budget(budget) or budget <= hold.total):
            return False
        with self._lock:
            if not hub.resume_budget(session, hold):
                return False
            now = self._clock()
            self._record(session, budget, now, self._active(session, now))
            return True

    def warnings(self) -> dict[str, BudgetUsage]:
        with self._lock:
            now = self._clock()
            result = {}
            for session, total in self._totals.items():
                record = self._active(session, now)
                if record is not None and record.budget not in record.warned:
                    usage = BudgetUsage(total, record.budget)
                    if usage.near_limit:
                        result[session] = usage
            return result

    def mark_warned(self, session: str, budget: int) -> None:
        with self._lock:
            record = self._active(session, self._clock())
            if record is not None:
                self._sessions[session] = SessionBudget(record.budget, record.last_active, record.warned | {budget})
                self._dirty = True

    def take_changes(self) -> dict[str, SessionBudget] | None:
        """Return a detached snapshot for the GUI's existing save scheduler."""
        with self._lock:
            now = self._clock()
            if now >= self._sweep_at:
                fresh = {s: r for s, r in self._sessions.items() if now - r.last_active < RETENTION}
                self._dirty |= len(fresh) != len(self._sessions)
                self._sessions = fresh
                self._totals = {s: total for s, total in self._totals.items() if s in fresh}
                self._sweep_at = min((r.last_active + RETENTION for r in fresh.values()),
                                     default=now + RETENTION)
            if self._dirty:
                self._dirty = False
                return dict(self._sessions)
            return None
