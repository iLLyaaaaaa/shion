"""Single background scanner, polled on the GUI thread. Never blocks hooks."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import threading
import time
import logging

from shion.usage import UsageScanner, load_cache


class UsageService:
    def __init__(self, directory):
        self.scanner = UsageScanner(directory / 'usage.json')
        self.data = load_cache(self.scanner.cache, self.scanner.pricing.signature())
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='weekly-usage')
        self.future = None
        self.cancel = threading.Event()
        self.due = None
        self.closed = False
        self.failed = False

    def request(self, delay=0):
        if not self.closed:
            due = time.monotonic() + delay
            self.due = due if self.due is None else min(self.due, due)

    def poll(self, enabled=True):
        changed = False
        if not enabled:
            self.cancel.set()
            self.due = None
        if self.future is not None and self.future.done():
            try:
                data = self.future.result()
                if data is not None and enabled:
                    self.data, changed = data, True
                    logging.getLogger('shion.usage').info('用量扫描完成：跳过 %s 条记录', self.scanner.skipped)
                self.failed = False
            except Exception:
                # Exception text may include transcript paths. Do not log it.
                self.failed = True
            self.future = None
        if enabled and not self.closed and self.future is None and self.due is not None and time.monotonic() >= self.due:
            self.cancel.clear()
            self.due = None
            self.future = self.executor.submit(self.scanner.scan, date.today(), self.cancel.is_set)
        return changed

    def close(self):
        self.closed = True
        self.cancel.set()
        self.executor.shutdown(wait=False, cancel_futures=True)
