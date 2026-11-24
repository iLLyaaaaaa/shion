"""Single background scanner, polled on the GUI thread. Never blocks hooks."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
import threading
import time
import logging

from shion.usage import UsageScanner, daily_tokens, load_cache

ACTIVE_REFRESH_SECONDS = 60


@dataclass(frozen=True)
class DailyReading:
    day: date
    total: int
    scanned_at: float


class UsageService:
    def __init__(self, directory):
        self.scanner = UsageScanner(directory / 'usage.json')
        self.data = load_cache(self.scanner.cache, self.scanner.pricing.signature())
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='weekly-usage')
        self.future = None
        self.daily_reading: DailyReading | None = None
        self._scan_day: date | None = None
        self._last_start = float('-inf')
        self.cancel = threading.Event()
        self.due = None
        self.closed = False
        self.failed = False

    def request(self, delay=0):
        if not self.closed:
            due = time.monotonic() + delay
            self.due = due if self.due is None else min(self.due, due)

    def poll(self, enabled=True, *, working=False, day=None):
        day = day or date.today()
        now = time.monotonic()
        changed = False
        if not enabled:
            self.cancel.set()
            self.due = None
        if not enabled or (self.daily_reading is not None and self.daily_reading.day != day):
            self.daily_reading = None
        if self.future is not None and self.future.done():
            try:
                data = self.future.result()
                if enabled and not self.cancel.is_set() and data is not None:
                    if self._scan_day == day:
                        self.daily_reading = DailyReading(day, daily_tokens(data, day), now)
                    self.data, changed = data, True
                    logging.getLogger('shion.usage').info('用量扫描完成：跳过 %s 条记录', self.scanner.skipped)
                else:
                    self.daily_reading = None
                self.failed = data is None and not self.cancel.is_set()
            except Exception:
                # Exception text may include transcript paths. Do not log it.
                self.daily_reading = None
                self.failed = True
            self.future = None
        requested = self.due is not None and now >= self.due
        periodic = working and now - self._last_start >= ACTIVE_REFRESH_SECONDS
        if enabled and not self.closed and self.future is None and (requested or periodic):
            self.cancel.clear()
            self.due = None
            self._scan_day = day
            self._last_start = now
            self.future = self.executor.submit(self.scanner.scan, day, self.cancel.is_set)
        return changed

    def close(self):
        self.closed = True
        self.cancel.set()
        self.executor.shutdown(wait=False, cancel_futures=True)
