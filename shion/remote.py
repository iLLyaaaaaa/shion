"""工作遥控的线程安全共享状态（纯 Python，不 import Qt）。

服务线程（长轮询的 hook 请求）和 GUI 线程（用户点按钮）都会碰它，所以用一个 Condition 保护。
这里只存“暂停”之类的标志；谁能改它由调用方决定：HTTP 服务只读、只等，不替用户做决定。
"""
from __future__ import annotations

import threading

MAX_WAIT = 30.0  # 单次长轮询最多等多久（秒）


class RemoteHub:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._paused = False

    # ---- 暂停 / 继续 ----
    @property
    def is_paused(self) -> bool:
        with self._cond:
            return self._paused

    def pause(self) -> None:
        with self._cond:
            self._paused = True
            self._cond.notify_all()

    def resume(self) -> None:
        with self._cond:
            self._paused = False
            self._cond.notify_all()

    def wait_while_paused(self, seconds: float) -> bool:
        """最多等 seconds 秒，直到不再暂停。返回结束时是否仍在暂停。"""
        seconds = max(0.0, min(float(seconds), MAX_WAIT))
        with self._cond:
            self._cond.wait_for(lambda: not self._paused, timeout=seconds)
            return self._paused
