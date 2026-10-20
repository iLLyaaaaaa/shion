"""QApplication、单实例检查、截图模式。"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QLocale, QObject, QStandardPaths
from PySide6.QtGui import QImage, QPainter
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from shion import state as state_mod
from shion.bridge import ServerBridge
from shion.bubble import CHAR_INTERVAL, GAP, BubbleWindow, place_bubble
from shion.controller import PetController
from shion.effects import HeartOverlay
from shion.lines import Lines, available_languages, resolve_language
from shion.remote import RemoteHub
from shion.pet_window import MARGIN_TOP, MARGIN_X, PetWindow
from shion.server import DEFAULT_PORT, ShionServer
from shion.speech import Priority

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
    """日志写进数据目录（1 MB 轮转，保留 2 份）。目录不可写时不能让桌宠起不来，只往 stderr 写。"""
    root = logging.getLogger("shion")
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            directory / "shion.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8"
        )
        fh.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
        root.addHandler(fh)
    except OSError as e:
        root.addHandler(logging.StreamHandler())
        root.warning("无法写日志文件（%s），改为只输出到 stderr", e)
        return
    if debug:
        root.addHandler(logging.StreamHandler())


def run() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Shion")
    app.setQuitOnLastWindowClosed(False)

    guard = SingleInstance(os.environ.get("SHION_INSTANCE_NAME") or INSTANCE_NAME, parent=app)
    if not guard.acquire():
        log.info("已有 Shion 在运行，退出")
        return 0

    debug = os.environ.get("SHION_DEBUG") == "1"
    directory = data_dir()
    setup_logging(directory, debug)
    save_path = directory / "state.json"
    first_start = not save_path.exists()

    now = datetime.now()
    data = state_mod.load(save_path)
    scheduler = state_mod.SaveScheduler(save_path, data)
    config = state_mod.Config.debug() if debug else state_mod.Config()
    pet_state = state_mod.PetState(data, now, config, on_change=scheduler.mark_dirty)

    win = PetWindow(height=data.window.get("height", 200), debug=debug)
    overlay = HeartOverlay()
    bubble = BubbleWindow()
    lang = resolve_language(
        data.language, QLocale().name(), [c for c, _ in available_languages()]
    )
    lines = Lines(lang)
    bubble.set_font_fallback(lines.font_fallback)
    hub = RemoteHub()
    controller = PetController(
        win, pet_state, scheduler, lines=lines, overlay=overlay, bubble=bubble, hub=hub, parent=app
    )
    if data.language != lines.lang:  # 首次启动：把跟随系统得到的语言记进存档
        data.language = lines.lang
        scheduler.mark_dirty(now)
    controller.quit_requested.connect(app.quit)

    # 本地 HTTP 服务：回调在服务线程里，经 ServerBridge 切回 GUI 线程
    bridge = ServerBridge(controller, parent=app)
    port = int(os.environ.get("SHION_PORT") or DEFAULT_PORT)
    server = ShionServer(bridge.on_event, bridge.on_take_feedback, port=port, hub=hub)
    server_ok = True
    try:
        server.start()
    except OSError as e:
        server_ok = False
        log.warning("HTTP 服务启动失败（端口 %s 被占用？）：%s", port, e)
    app.aboutToQuit.connect(server.stop)  # 先停服务，再写存档
    app.aboutToQuit.connect(scheduler.flush)

    controller.restore_position()
    win.show()
    log.info("Shion 启动，存档：%s", save_path)
    controller.greet_startup(first_start, from_hook=os.environ.get("SHION_LAUNCHED_BY_HOOK") == "1")
    if not server_ok:
        controller.say(lines.ui("port_busy", port=port), priority=Priority.HIGH, category="port_error")
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
    lang: str = "zh",
    from_state: str | None = None,
    jump: bool = False,
    turn: bool = False,
    drag: bool = False,
    face: str | None = None,
    cheek: str | None = None,
    tickle: bool = False,
) -> int:
    """离屏渲染一帧存成 PNG。不显示窗口，不做单实例检查。

    at：切到该状态后第几秒的那一帧（用来检查晃动、呼吸）。squash：在 0 秒触发压扁。
    bubble：同时画出头顶的气泡；此时 at 是气泡打字的进度，at=0 表示显示完整台词。
    from_state：从指定精灵淡化到 state，用 at 检查过渡的中间帧。
    """
    # 不强制 offscreen：offscreen 平台没有任何字体，中文会变成方块；
    # 原生平台不显示窗口也能渲染（测试里可用环境变量 QT_QPA_PLATFORM 覆盖）
    app = QApplication.instance() or QApplication(sys.argv)
    t = [100.0]  # 假时钟，不用真的等
    win = PetWindow(clock=lambda: t[0], autostart=False, debug=False)
    win.set_state(from_state or state, animate=False)
    if from_state:
        win.set_state(state)
    if squash:
        win._animator.squash(t[0], squash)
    if jump:
        win.jump()
    elif turn:
        win.turn()
    elif face:
        win.face(1 if face == "right" else -1)
    elif cheek:
        from shion.behavior import CHEEK_RELEASE_SECONDS
        win._pose = win._gesture_sprite("cheek", {"right": 1, "left": 2, "release": 3}[cheek], "stop")
        win._cheek_pulling = cheek != "release"
        win._pose_until = t[0] + CHEEK_RELEASE_SECONDS
    elif tickle:
        win._feed_tickle(t[0])
        win._tickle_last = t[0] + at  # 截图模拟一直在挠，不在一秒后停止
    elif drag:
        from shion.behavior import DragPlayback
        win.set_state("drag", animate=False)
        win._drag_playback = DragPlayback(t[0])
    t[0] += at
    win.advance_to(t[0])
    img = win.render_frame()

    if bubble:
        bt = [100.0]
        bw = BubbleWindow(clock=lambda: bt[0], autostart=False)
        bw.set_font_fallback(Lines(lang).font_fallback)
        bw.say(bubble)
        bt[0] += at if at > 0 else len(bubble) * CHAR_INTERVAL
        bimg = bw.render_image(bt[0])
        gap = GAP
        cw = max(img.width(), bimg.width())
        px = (cw - img.width()) // 2
        # 气泡可占用画布顶部留边；腾空时留足空间，避免遮到头顶。
        body_top = MARGIN_TOP - round(win._jump_offset)
        py = max(0, bimg.height() + gap - body_top)
        ch = bimg.height() + gap + img.height()
        sw, sh = win.sprite_size
        body = (px + MARGIN_X, py + body_top, sw, sh)
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


def snapshot_panel(out: str, kind: str, text: str = "git status", lang: str = "zh",
                   more: int = 0, expand: bool = False) -> int:
    """离屏渲染遥控面板存成 PNG（自查画面用）。同意/否决面板的按钮在 0.6 秒内是灰的，截图时按“已生效”画。"""
    from shion.panel import ARM_DELAY, InputPanel, PermissionPanel

    app = QApplication.instance() or QApplication(sys.argv)
    lines = Lines(lang)
    ui = lines.ui
    font_bubble = BubbleWindow()
    font_bubble.set_font_fallback(lines.font_fallback)
    family = font_bubble.font_family
    body = (400, 400, 100, 100)
    if kind == "eating":
        from shion.effects import CrumbOverlay, MOUTH_FRACTION
        win = PetWindow(autostart=False, debug=False)
        win.set_state("happy", animate=False)
        img = win.render_frame()
        t = [100.0]
        panel = CrumbOverlay(clock=lambda: t[0], autostart=False)
        panel.start(win.head_anchor(), 200)
        for elapsed in (0.16, 0.32, 0.35):
            t[0] = 100.0 + elapsed
            panel.tick()
        crumbs = QImage(panel.size(), QImage.Format_ARGB32_Premultiplied)
        crumbs.fill(0)
        panel.render(crumbs)
        p = QPainter(img)
        sw, sh = win.sprite_size
        p.drawImage(MARGIN_X + sw // 2 - panel.SIZE // 2, MARGIN_TOP + round(sh * MOUTH_FRACTION) - 40, crumbs)
        p.end()
        win.close()
    elif kind in ("dialogue", "snacks"):
        from shion.dialogue import DialoguePanel
        from shion.menu_content import MenuContent
        panel = DialoguePanel(MenuContent(), lines, family)
        panel.open(body)
        if kind == "snacks":
            panel._choose("page", "snacks")
        img = panel.grab().toImage()
    elif kind == "input":
        panel = InputPanel(family)
        panel.open(ui("panel_bad_title"), ui("panel_send"), ui("panel_cancel"), body)
        img = panel.grab().toImage()
    else:
        t = [0.0]
        panel = PermissionPanel(family, clock=lambda: t[0])
        panel.show_request(
            "snapshot", "Bash", text, more,
            {"title": ui("permission_title"), "allow": ui("permission_allow"), "deny": ui("permission_deny"),
             "more": ui("permission_more"), "expand": ui("permission_expand"),
             "collapse": ui("permission_collapse")},
            body,
        )
        if expand:
            panel._toggle.click()
        t[0] += ARM_DELAY + 0.1
        panel.refresh_enabled()
        img = panel.grab().toImage()
    font_bubble.close()
    panel.hide()
    panel.setParent(None)
    panel.deleteLater()  # 在这里（GUI 线程）立刻销毁，别留给别的线程里的垃圾回收
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    ok = img.save(out, "PNG")
    if not ok:
        print(f"保存失败：{out}", file=sys.stderr)
        return 1
    print(f"saved {out} ({img.width()}x{img.height()})")
    del app
    return 0
