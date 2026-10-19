"""QApplication、单实例检查、截图模式。"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QStandardPaths
from PySide6.QtGui import QImage, QPainter
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from shion import state as state_mod
from shion.bubble import CHAR_INTERVAL, GAP, BubbleWindow, place_bubble
from shion.controller import PetController
from shion.effects import HeartOverlay
from shion.pet_window import MARGIN_TOP, MARGIN_X, PetWindow

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


def data_dir() -> Path:
    """存档和日志目录：%APPDATA%/Shion（环境变量 SHION_DATA_DIR 可覆盖，测试用）。"""
    override = os.environ.get("SHION_DATA_DIR")
    if override:
        return Path(override)
    return Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))


def setup_logging(directory: Path, debug: bool) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("shion")
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    fh = logging.FileHandler(directory / "shion.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    root.addHandler(fh)
    if debug:
        root.addHandler(logging.StreamHandler())


def run() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Shion")
    app.setQuitOnLastWindowClosed(False)

    guard = SingleInstance(parent=app)
    if not guard.acquire():
        log.info("已有 Shion 在运行，退出")
        return 0

    debug = os.environ.get("SHION_DEBUG") == "1"
    directory = data_dir()
    setup_logging(directory, debug)
    save_path = directory / "state.json"

    now = datetime.now()
    data = state_mod.load(save_path)
    scheduler = state_mod.SaveScheduler(save_path, data)
    config = state_mod.Config.debug() if debug else state_mod.Config()
    pet_state = state_mod.PetState(data, now, config, on_change=scheduler.mark_dirty)

    win = PetWindow(height=data.window.get("height", 240))
    overlay = HeartOverlay()
    bubble = BubbleWindow()
    controller = PetController(
        win, pet_state, scheduler, overlay=overlay, bubble=bubble, parent=app
    )
    controller.quit_requested.connect(app.quit)
    app.aboutToQuit.connect(scheduler.flush)
    controller.restore_position()
    win.show()
    log.info("Shion 启动，存档：%s", save_path)
    code = app.exec()
    scheduler.flush()
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
    bubble：同时画出头顶的气泡；此时 at 是气泡打字的进度，at=0 表示显示完整台词。
    """
    # 不强制 offscreen：offscreen 平台没有任何字体，中文会变成方块；
    # 原生平台不显示窗口也能渲染（测试里可用环境变量 QT_QPA_PLATFORM 覆盖）
    app = QApplication.instance() or QApplication(sys.argv)
    t = [100.0]  # 假时钟，不用真的等
    win = PetWindow(clock=lambda: t[0], autostart=False)
    win.set_state(state)
    if squash:
        win._animator.squash(t[0], squash)
    t[0] += at
    win.advance_to(t[0])
    img = win.render_frame()

    if bubble:
        bt = [100.0]
        bw = BubbleWindow(clock=lambda: bt[0], autostart=False)
        bw.say(bubble)
        bt[0] += at if at > 0 else len(bubble) * CHAR_INTERVAL
        bimg = bw.render_image(bt[0])
        gap = GAP
        cw = max(img.width(), bimg.width())
        ch = bimg.height() + gap + img.height()
        px = (cw - img.width()) // 2
        py = bimg.height() + gap
        sw, sh = win.sprite_size
        body = (px + MARGIN_X, py + MARGIN_TOP, sw, sh)
        bx, by = place_bubble(body, (bimg.width(), bimg.height()), (0, 0, cw, ch))
        canvas = QImage(cw, ch, QImage.Format_ARGB32_Premultiplied)
        canvas.fill(0)
        p = QPainter(canvas)
        p.drawImage(px, py, img)
        p.drawImage(bx, by, bimg)
        p.end()
        img = canvas

    ok = img.save(out, "PNG")
    if not ok:
        print(f"保存失败：{out}", file=sys.stderr)
        return 1
    print(f"saved {out} ({img.width()}x{img.height()})")
    del app
    return 0
