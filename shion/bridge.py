"""把 HTTP 服务线程和 GUI 线程接起来。

ShionServer 的回调在服务线程里被调用，而状态机和界面只能在 GUI 线程动。
这里用 Qt 信号（自动排队到接收者所在的线程）做切换：
- 事件：发信号就返回，不阻塞服务线程；
- 夸奖：服务线程要同步拿返回值，所以放一个请求对象，等 GUI 线程填好结果；
  超时就抛 TimeoutError（server 会回 500），避免 GUI 线程卡住或正在退出时一直挂着。
"""
from __future__ import annotations

import threading
from typing import Optional

from PySide6.QtCore import QObject, Signal

from shion.controller import PetController

TAKE_TIMEOUT = 2.0  # 秒


class _PraiseRequest:
    def __init__(self) -> None:
        self.done = threading.Event()
        self.count = 0


class ServerBridge(QObject):
    event_received = Signal(str, object)
    praise_requested = Signal(object)

    def __init__(self, controller: PetController, take_timeout: float = TAKE_TIMEOUT,
                 parent: Optional[QObject] = None):
        super().__init__(parent)  # 必须在 GUI 线程创建，信号才会排队切到这里
        self._controller = controller
        self._take_timeout = take_timeout
        self.event_received.connect(self._handle_event)
        self.praise_requested.connect(self._handle_praise)

    # ---- 给 ShionServer 用，在服务线程里调用 ----
    def on_event(self, etype: str, detail: Optional[str]) -> None:
        self.event_received.emit(etype, detail)

    def on_take_praise(self) -> int:
        req = _PraiseRequest()
        self.praise_requested.emit(req)
        if not req.done.wait(self._take_timeout):
            raise TimeoutError("GUI 线程没有及时处理夸奖请求")
        return req.count

    # ---- 在 GUI 线程里执行 ----
    def _handle_event(self, etype: str, detail) -> None:
        self._controller.handle_event(etype, detail)

    def _handle_praise(self, req: _PraiseRequest) -> None:
        try:
            req.count = self._controller.take_praise()
        finally:
            req.done.set()
