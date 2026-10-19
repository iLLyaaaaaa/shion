"""QApplication、单实例检查、截图模式。"""
from __future__ import annotations

import logging
import os
import sys

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from shion.pet_window import PetWindow

log = logging.getLogger("shion")

INSTANCE_NAME = "ShionDesktopPet-single-instance"


class SingleInstance(QObject):
    """用本地套接字保证只有一个实例。"""

    def __init__(self, name: str = INSTANCE_NAME, parent: QObject | None = None):
        super().__init__(parent)
        self._name = name
        self._server: QLocalServer | None = None

    def acquire(self) -> bool:
        """True = 我是第一个实例；False = 已有实例在运行。"""
        sock = QLocalSocket()
        sock.connectToServer(self._name)
        if sock.waitForConnected(300):
            sock.disconnectFromServer()
            return False
        QLocalServer.removeServer(self._name)  # 清理上次崩溃留下的残留
        self._server = QLocalServer(self)
        return self._server.listen(self._name)

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None


def run() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Shion")
    app.setQuitOnLastWindowClosed(False)

    guard = SingleInstance(parent=app)
    if not guard.acquire():
        log.info("已有 Shion 在运行，退出")
        return 0

    win = PetWindow()
    win.quit_requested.connect(app.quit)
    win.place_default()
    win.show()
    code = app.exec()
    guard.release()
    return code


def snapshot(
    out: str,
    state: str = "idle",
    bubble: str | None = None,
    at: float = 0.0,
    squash: str | None = None,
) -> int:
    """离屏渲染一帧存成 PNG。不显示窗口，不做单实例检查。

    at：切到该状态后第几秒的那一帧（用来检查晃动、呼吸）。squash：在 0 秒触发压扁。
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv)
    if bubble:
        print("提示：气泡还没实现（第 5 步），--bubble 被忽略", file=sys.stderr)
    t = [100.0]  # 假时钟，不用真的等
    win = PetWindow(clock=lambda: t[0], autostart=False)
    win.set_state(state)
    if squash:
        win._animator.squash(t[0], squash)
    t[0] += at
    win.advance_to(t[0])
    ok = win.render_frame().save(out, "PNG")
    if not ok:
        print(f"保存失败：{out}", file=sys.stderr)
        return 1
    print(f"saved {out} ({win.width()}x{win.height()})")
    del app
    return 0
