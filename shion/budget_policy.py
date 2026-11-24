"""Budget state shared by the checkpoint service and the GUI."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
import logging
from threading import Lock
from time import monotonic

from shion.remote import BudgetPause, RemoteHub
from shion.state import DailyBudget, SessionBudget, valid_budget
from shion.usage_service import DailyReading

RETENTION = timedelta(days=7)
BUDGET_TIERS = (10_000_000, 50_000_000, 100_000_000)
DAILY_BUDGET_TIERS = (50_000_000, 100_000_000, 200_000_000)
log = logging.getLogger('shion.budget')


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
    def __init__(self, default=None, sessions=None, *, daily_default=None, daily=None, clock=datetime.now):
        self._clock = clock
        self._lock = Lock()
        self._default = default
        self._sessions = dict(sessions or {})
        self._totals: dict[str, int] = {}
        self._dirty = False
        self._sweep_at = datetime.min
        self._daily_default = daily_default
        self._daily_state = daily
        self._daily_reading: DailyReading | None = None
        self._last_daily_reading: DailyReading | None = None

    def _day_state(self, day):
        state = self._daily_state
        return state if state is not None and state.day == day else DailyBudget(day)

    def _daily_usage(self, day):
        state = self._day_state(day)
        budget = state.override if state.has_override else self._daily_default
        reading = self._daily_reading
        if reading is None or reading.day != day:
            return BudgetUsage(None, budget), None
        return BudgetUsage(reading.total, budget), max(0, monotonic() - reading.scanned_at)

    def daily_usage(self) -> BudgetUsage:
        with self._lock:
            return self._daily_usage(self._clock().date())[0]

    @property
    def daily_state(self) -> DailyBudget | None:
        with self._lock:
            return self._daily_state

    def set_daily_reading(self, reading: DailyReading | None) -> None:
        with self._lock:
            self._daily_reading = reading
            if reading is not None:
                self._last_daily_reading = reading

    def _held_daily_total(self, hold):
        reading = self._last_daily_reading
        return reading.total if reading is not None and reading.day == hold.day else hold.total

    def held_daily_usage(self, hold: BudgetPause) -> BudgetUsage:
        with self._lock:
            budget = self._daily_usage(hold.day)[0].budget
            return BudgetUsage(self._held_daily_total(hold), budget if budget is not None else hold.budget)

    def set_daily_default(self, value: int | None, hub: RemoteHub) -> None:
        if value is not None and not valid_budget(value):
            raise ValueError("budget must be a positive integer or None")
        with self._lock:
            day = self._clock().date()
            self._daily_default = value
            if self._daily_state is not None and self._daily_state.has_override:
                self._daily_state = replace(self._day_state(day), override=None, has_override=False)
            hub.clear_daily_budgets(keep_day=day)
            hold = next((hold for hold in hub.budget_pauses().values() if hold.day == day), None)
            if hold is not None and (value is None or value > self._held_daily_total(hold)):
                hub.resolve_daily_budget(hold)

    def choose_daily(self, hold: BudgetPause, budget: int | None, hub: RemoteHub) -> bool:
        with self._lock:
            day = self._clock().date()
            if hold.day != day or (budget is not None and (
                    not valid_budget(budget) or budget <= self._held_daily_total(hold))):
                return False
            if not hub.resolve_daily_budget(hold):
                return False
            self._daily_state = replace(self._day_state(day), override=budget, has_override=True)
            return True

    def daily_warning(self, day) -> BudgetUsage | None:
        with self._lock:
            usage, _ = self._daily_usage(day)
            if usage.near_limit and usage.budget not in self._day_state(day).warned:
                return usage
            return None

    def mark_daily_warned(self, day, budget: int) -> None:
        with self._lock:
            state = self._day_state(day)
            self._daily_state = replace(state, warned=state.warned | {budget})

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

    def observe(self, session: str, total: int | None, hub: RemoteHub, *,
                checkpoint_started: float = float('inf')) -> bool:
        """Update the session reading and check the cached daily limit first."""
        with self._lock:
            now = self._clock()
            day = now.date()
            hub.clear_daily_budgets(keep_day=day)
            budget = None
            if total is not None:
                record = self._active(session, now)
                budget = record.budget if record else self._default
                self._record(session, budget, now, record)
                self._totals[session] = total
            daily, age = self._daily_usage(day)
            daily_hit = daily.total is not None and daily.budget is not None and daily.total >= daily.budget
            if daily_hit:
                hold = BudgetPause(daily.total, daily.budget, day)
            elif budget is not None and total >= budget:
                hold = BudgetPause(total, budget)
            else:
                hold = None
            paused = hold is not None and hub.pause(session, budget=hold, checkpoint_started=checkpoint_started)
        log.info("每日预算判断 今日用量=%s 上限=%s 数据距今=%s 结果=%s",
                 daily.total if daily.total is not None else "未知",
                 daily.budget if daily.budget is not None else "不限",
                 f"{age:.1f} 秒" if age is not None else "未知",
                 "达到上限" if daily_hit else "放行" if age is not None else "用量未知")
        return paused

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
