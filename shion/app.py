"""QApplication、单实例检查、截图模式。"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
import math
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QCoreApplication, QEvent, QLocale, QObject, QPoint, QPointF, QRect, QSize, QStandardPaths, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from shion import state as state_mod
from shion import __version__
from shion.icons import ICON_SIZES, application_icon
from shion.launcher import INSTANCE_NAME  # 单实例管道名；hook 用同一个常量判断诗音是否在运行
from shion.bridge import ServerBridge
from shion.bubble import CHAR_INTERVAL, GAP, BubbleWindow, place_bubble
from shion.controller import PetController
from shion.effects import HeartOverlay
from shion.lines import Lines, available_languages, resolve_language
from shion.remote import RemoteHub
from shion.pet_window import MARGIN_TOP, MARGIN_X, PetWindow
from shion.permission_text import permission_summary
from shion.server import DEFAULT_PORT, LINK_PORT_BUSY, LINK_TOKEN_FAILED, ShionServer, start_linked, stop_linked
from shion.speech import Priority

log = logging.getLogger("shion")


ERROR_ALREADY_EXISTS = 183


def _create_mutex(name: str):
    """(句柄, 是否已存在)。句柄为 0 表示创建失败。Qt 6 在 Windows 上允许两个 QLocalServer 监听同一个管道名，
    几个进程同时启动会都认为自己是第一个；命名互斥锁的创建是原子的，所以用它判定唯一实例。"""
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    ctypes.set_last_error(0)
    handle = kernel32.CreateMutexW(None, False, "Local\\" + name)
    if not handle:
        return 0, False
    return handle, ctypes.get_last_error() == ERROR_ALREADY_EXISTS


def _close_handle(handle) -> None:
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle(handle)


class SingleInstance(QObject):
    """只有一个实例：Windows 上先抢命名互斥锁（原子），再用本地套接字服务器让已有实例可被连到。

    套接字服务器仍然保留：hook / Codex 观察端用它的管道判断诗音有没有开，旧版没有互斥锁的实例也靠它识别。
    """

    def __init__(self, name: str = INSTANCE_NAME, parent: QObject | None = None):
        super().__init__(parent)
        self._name = name
        self._server: QLocalServer | None = None
        self._mutex = 0  # 拿到锁的实例在整个生命周期内持有句柄

    def _notify_existing(self) -> bool:
        """连一下已有实例的服务器再断开；连上了说明确实有实例在运行。"""
        sock = QLocalSocket()
        sock.connectToServer(self._name)
        if sock.waitForConnected(300):
            sock.disconnectFromServer()
            return True
        return False

    def acquire(self) -> bool:
        """True = 我是第一个实例；False = 已有实例在运行。"""
        if sys.platform == "win32":
            try:
                handle, exists = _create_mutex(self._name)
            except Exception:
                log.exception("创建单实例互斥锁失败，退回只用套接字判断")
                handle, exists = 0, False
            if exists:
                _close_handle(handle)
                self._notify_existing()
                return False
            self._mutex = handle
        if self._notify_existing():  # 旧版实例没有互斥锁，只能靠它的服务器识别
            self._release_mutex()
            return False
        QLocalServer.removeServer(self._name)  # 清理上次崩溃留下的残留
        self._server = QLocalServer(self)
        if self._server.listen(self._name):
            return True
        self._server = None
        self._release_mutex()
        return False

    def _release_mutex(self) -> None:
        handle, self._mutex = self._mutex, 0
        if handle:
            _close_handle(handle)

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        self._release_mutex()


def data_dir() -> Path:
    """存档和日志目录：%APPDATA%/Shion（环境变量 SHION_DATA_DIR 可覆盖，测试用）。"""
    override = os.environ.get("SHION_DATA_DIR")
    if override:
        return Path(override)
    if os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "Shion"
    return Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))


def link_warning(status: str, ui, port: int) -> Optional[str]:
    """启动时联动服务的问题提示（start_linked 的返回值）；没问题返回 None。"""
    if status == LINK_PORT_BUSY:
        return ui("port_busy", port=port)
    if status == LINK_TOKEN_FAILED:
        return ui("link_token_failed")
    return None


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
    app.setApplicationVersion(__version__)
    app.setWindowIcon(application_icon())
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
    from shion.affection import load_rules
    pet_state = state_mod.PetState(data, now, config, on_change=scheduler.mark_dirty, affection=load_rules())

    height = data.window.get("height", 200)
    # 按存档位置先猜鼓哪一侧，免得先建一侧再丢掉（首次显示仍会按真实位置核对）
    from shion.v3_display import startup_side
    from shion.v3_window import V3PetWindow
    rects = []
    for screen in QGuiApplication.screens():
        g = screen.availableGeometry()
        rects.append((g.x(), g.y(), g.width(), g.height()))
    side = startup_side(data.window.get("x"), data.window.get("y"), height, rects)
    win = V3PetWindow(height=height, debug=debug, initial_side=side)
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
    app.aboutToQuit.connect(controller.usage.close)
    from shion.chatgpt import ChatGPTConnection
    controller.chatgpt = ChatGPTConnection(directory)
    controller.chatgpt.start()
    app.aboutToQuit.connect(controller.chatgpt.stop)

    # 本地 HTTP 服务：回调在服务线程里，经 ServerBridge 切回 GUI 线程
    bridge = ServerBridge(controller, parent=app)
    port = int(os.environ.get("SHION_PORT") or DEFAULT_PORT)
    server = ShionServer(bridge.on_event, bridge.on_take_feedback, port=port, hub=hub,
                         usage_enabled=lambda: data.usage_enabled, budget_policy=controller.budget_policy)
    # 绑定成功才写令牌；端口被占时不写，hook 就不会去连占着端口的进程
    link_status = start_linked(server, directory)
    app.aboutToQuit.connect(lambda: stop_linked(server, directory))  # 先删令牌、停服务，再写存档
    app.aboutToQuit.connect(controller.sync_budget_save)
    app.aboutToQuit.connect(scheduler.flush)

    controller.restore_position()
    win.show()
    tray = controller.create_tray()
    if tray is not None:
        app.aboutToQuit.connect(tray.hide)
    log.info("tray=%s", "unavailable" if tray is None else
             "visible" if tray.isVisible() and not tray.icon().isNull() else "failed")
    log.info("Shion 启动，存档：%s", save_path)
    controller.greet_startup(first_start, from_hook=os.environ.get("SHION_LAUNCHED_BY_HOOK") == "1")
    warning = link_warning(link_status, lines.ui, port)
    if warning:
        controller.say(warning, priority=Priority.HIGH, category="port_error")
    code = app.exec()
    scheduler.flush()
    guard.release()
    return code


def render_pet_snapshot(win: PetWindow, scale: int = 1) -> QImage:
    """当前宠物帧与睡眠特效；单帧截图和连续媒体共用，不推进时钟。"""
    img = win.render_frame(scale)
    if win._sleep_z is not None:
        from shion.effects import sleep_z_anchor
        painter = QPainter(img)
        win._sleep_z.draw(painter, QPointF(win.mapFromGlobal(sleep_z_anchor(win, win._sleep_z.state))))
        painter.end()
    return img


def render_widget_image(widget, scale: int = 1) -> QImage:
    """直接画到目标像素密度，不读取桌面或受窗口遮罩裁剪。"""
    img = QImage(widget.size() * scale, QImage.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(scale)
    img.fill(0)
    painter = QPainter(img)
    try:
        widget.render(painter, QPoint())
    finally:
        painter.end()
    return img


class SnapshotScene:
    """一次创建、按假时钟连续取帧。调用者负责触发动作和 close。"""

    def __init__(self, state: str = "idle", height: int = 200, activity: str = "normal",
                 *, seed: int | None = None, scale: int = 1, side: str | None = None):
        from shion.v3_window import V3PetWindow
        self.app = QApplication.instance() or QApplication(sys.argv)
        self.time = [100.0]
        self.scale = scale
        self.win = V3PetWindow(height=height, clock=lambda: self.time[0], autostart=False,
                               debug=False, rng=random.Random(seed) if seed is not None else None,
                               pixel_ratio=scale if seed is not None or scale != 1 else None,
                               initial_side=side)
        if side is not None:
            self.win.auto_side = False  # 截图指定了鼓哪一侧：不要再按位置换边
        self.win.setAttribute(Qt.WA_DontShowOnScreen)
        self.win.set_activity(activity)
        self.win.set_calm(activity == "quiet")
        self.win.set_state(state, animate=False)

    def advance_to(self, elapsed: float) -> None:
        target = 100.0 + elapsed
        if not math.isfinite(target) or target < self.time[0]:
            raise ValueError("截图时间必须有限且单调递增")
        self.time[0] = target
        self.win.advance_to(target)

    def render(self) -> QImage:
        return render_pet_snapshot(self.win, self.scale)

    def close(self) -> None:
        self.win.close()
        self.win.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


GESTURES = ("pinch", "pat", "knock", "tickle", "lift")
SIDES = ("left", "right")


def apply_snapshot_gesture(win, gesture: str, at: float) -> None:
    """让真实窗口的 V3 动画器按确定性输入走到手势的第 at 秒（输入来自 v3proto 的 *_scenario）。"""
    animator = win._v3_animator
    pivot = (325.0, 586.0) if win._v3_side == "left" else (543.0, 586.0)  # 脸颊按下点（与窗口的默认拎起支点一致）
    if gesture == "pinch":
        start = animator.clock
        animator.press(pivot, now=start)
        steps = max(1, round(at * 60))
        for i in range(steps + 1):
            moment = at * i / steps
            animator.advance(max(0.0, moment - (at * (i - 1) / steps if i else 0.0)), now=start + moment)
            reach = min(1.0, moment / 0.3)
            animator.drag((pivot[0] - 70.0 * reach, pivot[1]))
    elif gesture == "pat":
        from v3proto.head_scenarios import head_scenario
        head_scenario(animator, "pat-right", at)
    elif gesture == "knock":
        from v3proto.head_scenarios import head_scenario
        head_scenario(animator, "knock", at)
    elif gesture == "tickle":
        from v3proto.tickle_scenarios import tickle_scenario
        tickle_scenario(animator, "rub", at)
    elif gesture == "lift":
        from v3proto.lift_scenarios import lift_scenario
        lift_scenario(animator, "held", at, pivot)
    else:
        raise ValueError(f"未知手势：{gesture}")


def render_snapshot(*args, **kwargs) -> QImage:
    """离屏渲染一帧并返回 QImage（参数见 _render_snapshot）。V3 的预热在当前线程里做完，截图才确定。"""
    import shion.v3_window as v3_window
    from shion.v3_prewarm import InlineExecutor

    previous = v3_window.PREWARM_EXECUTOR
    v3_window.PREWARM_EXECUTOR = InlineExecutor()
    try:
        return _render_snapshot(*args, **kwargs)
    finally:
        v3_window.PREWARM_EXECUTOR = previous


def _render_snapshot(
    state: str = "idle",
    bubble: str | None = None,
    at: float = 0.0,
    squash: str | None = None,
    lang: str = "zh",
    from_state: str | None = None,
    jump: bool = False,
    badge: bool = False,
    height: int = 200,
    activity: str = "normal",
    nod: bool = False,
    gesture: str | None = None,
    side: str | None = None,
    chips: str | None = None,
    chips_side: str | None = None,
    chips_overlays: str | None = None,
) -> QImage:
    """离屏渲染一帧并返回 QImage。不显示窗口，不做单实例检查。

    at：切到该状态后第几秒的那一帧（用来检查晃动、呼吸）。squash：在 0 秒触发压扁。
    bubble：同时画出头顶的气泡；此时 at 是气泡打字的进度，at=0 表示显示完整台词。
    from_state：从指定精灵淡化到 state，用 at 检查过渡的中间帧。
    gesture：pinch / pat / knock / tickle / lift，让动画器按确定性输入走到手势的第 at 秒。
    side：left / right，鼓脸颊的一侧（不换边）。
    """
    # 不强制 offscreen：offscreen 平台没有任何字体，中文会变成方块；
    # 原生平台不显示窗口也能渲染（测试里可用环境变量 QT_QPA_PLATFORM 覆盖）
    scene = SnapshotScene(from_state or state, height, activity, side=side)
    t, win = scene.time, scene.win
    if from_state:
        win.set_state(state)
    if squash:
        win._animator.squash(t[0], squash)
    if jump:
        win.jump()
    elif gesture:
        apply_snapshot_gesture(win, gesture, at)
    elif nod:
        win._animator._nod_at = t[0]
    # 截图重建睡眠的发射时刻；正式运行掉帧时仍不补发历史粒子。
    if win._sleep_z is not None and win._sleep_z.particles.sleeping:
        from shion.effects import Z_INTERVAL
        index = 1
        while index * Z_INTERVAL < at:
            win._sleep_z.advance(t[0] + index * Z_INTERVAL, win._sleep_z.state)
            index += 1
    if chips == "demo":
        try:
            return render_task_chips_demo(scene, lang, chips_side, chips_overlays, bubble, badge, at)
        finally:
            scene.close()
    t[0] += at
    win.advance_to(t[0])
    img = scene.render()
    if badge:  # 暂停文字标签：与真实窗口一样相对精灵本体定位
        from shion.badge import badge_geometry, label_font, render_badge
        sw, sh = win.sprite_size
        lines = Lines(lang)
        label = render_badge(lines.ui("pause_label"), label_font(lines.font_fallback))
        size = (label.width(), label.height())
        bx, by = badge_geometry((MARGIN_X, MARGIN_TOP, sw, sh), size, (0, 0, img.width(), img.height()),
                                win._jump_offset)
        p = QPainter(img)
        p.drawImage(bx, by, label)
        p.end()

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
        bw.close()
        bw.deleteLater()

    scene.close()
    return img


def render_task_chips_demo(scene, lang, side, overlays, bubble_text, badge, at):
    """Compose live widgets on a fixed virtual screen so previews work on either side."""
    from shion.activity import Entry
    from shion.badge import CheckpointPanel, PauseBadge
    from shion.panel import ARM_DELAY, PermissionPanel
    from shion.sessions import SessionNames
    from shion.task_board import BoardInputs, TaskBoard
    from shion.task_chips import TaskChips
    from shion.tasks import TaskRecord

    pet = scene.win
    avail = QRect(0, 0, 1440, 900)
    center_x = 940 if side == "left" else 500
    pet.move(center_x - pet.width() // 2, 340)
    pet.show()
    scene.advance_to(at)

    lines = Lines(lang)
    ui = lines.ui
    labels = SessionNames()
    for key, label in (("review", "review"), ("build", "build"), ("docs", "docs"), ("tests", "tests")):
        labels.note(key, label)
    board = TaskBoard()
    now = scene.time[0]
    board.note_cc_stop("docs", ended_by_shion=False, now=now - 2)
    board.note_cc_stop("tests", ended_by_shion=False, now=now - 1)
    board.note_cc_tool("build", "demo", Entry(datetime.min, "working", "edit", "hello.py"))
    view = board.snapshot(BoardInputs(
        cc_permissions=("review",), cc_working=("build",),
        ledger_tasks={("chatgpt", "demo", "session", "turn"): TaskRecord("observed_working", now - 5)},
    ), now=now, session_names=labels, ui=ui)

    widgets = []
    def hidden(widget):
        widget.setAttribute(Qt.WA_DontShowOnScreen)
        widgets.append(widget)
        return widget

    try:
        if bubble_text or overlays:
            bubble = hidden(BubbleWindow(clock=lambda: now, autostart=False))
            bubble.set_font_fallback(lines.font_fallback)
            bubble.follow(pet.body_rect())
            bubble.say(bubble_text or ui("permission_title"), sticky=True)
        if badge or overlays == "pause":
            pause = hidden(PauseBadge(pet))
            pause.set_texts(ui("pause_label"), ui("pause_label_hint"), lines.font_fallback)
            pause.set_wanted(True)
        if overlays == "checkpoints":
            checkpoints = hidden(CheckpointPanel(pet, lines.font_fallback))
            checkpoints.present([("docs", "docs"), ("tests", "tests")],
                                {"title": ui("checkpoint_title"), "resume": ui("checkpoint_resume"),
                                 "end": ui("checkpoint_end")})
        if overlays:
            permission_clock = [now]
            permission = hidden(PermissionPanel(bubble.font_family, clock=lambda: permission_clock[0]))
            permission.show_request("demo", "Bash", "git status", 0, {
                key: ui("permission_" + key) for key in
                ("title", "allow", "deny", "more", "collapse")
            } | {"expand": ui("permission_details"), "command_warning": ui("permission_command_warning")},
                pet.body_rect(),
                summary=permission_summary("Bash", "git status", ui))
            permission_clock[0] += ARM_DELAY + 0.1
            permission.refresh_enabled()
        chips = hidden(TaskChips(pet, available=lambda _point: avail))
        chips.present(view, ui, lines.font_fallback, tuple(widgets[:-1]))
        if not chips.isVisible():
            raise RuntimeError("Task chips demo has no available layout")

        pet_bounds = pet.geometry()
        overlay = pet._v3_scene_overlay
        if overlay is not None and overlay.isVisible():
            pet_bounds = pet_bounds.united(overlay.geometry())
        assert all(not chips.geometry().intersects(rect)
                   for rect in (pet.visible_sprite_bounds(), *(w.geometry() for w in widgets[:-1])))
        layers = [(pet_bounds, scene.render())]
        for widget in widgets:
            image = (widget.render_image(now + 10) if isinstance(widget, BubbleWindow)
                     else render_widget_image(widget))
            layers.append((widget.geometry(), image))
        bounds = pet_bounds
        for rect, _image in layers[1:]:
            bounds = bounds.united(rect)
        bounds.adjust(-12, -12, 12, 12)
        image = QImage(bounds.size(), QImage.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        try:
            for rect, layer in layers:
                painter.drawImage(rect.topLeft() - bounds.topLeft(), layer)
        finally:
            painter.end()
        return image
    finally:
        for widget in reversed(widgets):
            widget.hide()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def snapshot(
    out: str, state: str = "idle", bubble: str | None = None, at: float = 0.0,
    squash: str | None = None, lang: str = "zh", from_state: str | None = None,
    jump: bool = False, badge: bool = False, height: int = 200,
    activity: str = "normal", nod: bool = False,
    gesture: str | None = None, side: str | None = None,
    chips: str | None = None, chips_side: str | None = None, chips_overlays: str | None = None,
) -> int:
    """原单帧 PNG 入口；参数、保存格式和终端输出保持不变。"""
    img = render_snapshot(state, bubble, at, squash, lang, from_state, jump, badge, height, activity,
                          nod, gesture, side, chips, chips_side, chips_overlays)

    ok = img.save(out, "PNG")
    if not ok:
        print(f"保存失败：{out}", file=sys.stderr)
        return 1
    print(f"saved {out} ({img.width()}x{img.height()})")
    return 0


def snapshot_icon_preview(out: str) -> int:
    """用真实 Qt 图标入口生成各尺寸在浅色/深色背景上的截图。"""
    app = QApplication.instance() or QApplication(sys.argv)
    icon = application_icon()
    img = QImage(760, 810, QImage.Format_ARGB32_Premultiplied)
    painter = QPainter(img)
    painter.setFont(QFont("Segoe UI", 10))
    for column, (background, foreground) in enumerate((("#f4f0eb", "#35221b"), ("#25211f", "#f4f0eb"))):
        left = column * 380
        painter.fillRect(left, 0, 380, img.height(), QColor(background))
        painter.setPen(QColor(foreground))
        painter.drawText(left + 16, 24, f"Shion {__version__} / {'Light' if column == 0 else 'Dark'}")
        top = 40
        for size in ICON_SIZES:
            painter.drawText(left + 16, top + 15, f"{size} x {size} / 1:1")
            frame = icon.pixmap(QSize(size, size), 1.0).toImage()
            painter.drawImage(left + 20, top + 24, frame)
            if size <= 32:
                painter.drawImage(left + 140, top + 24, frame.scaled(size * 4, size * 4,
                                  Qt.IgnoreAspectRatio, Qt.FastTransformation))
                painter.drawText(left + 140, top + 18, "4x pixels")
            top += max(size, size * 4 if size <= 32 else size) + 40
    painter.end()
    if not img.save(out, "PNG"):
        return 1
    print(f"saved {out} ({img.width()}x{img.height()})")
    return 0


def render_snapshot_panel(kind: str, text: str = "git status", lang: str = "zh",
                          more: int = 0, expand: bool = False, with_pet: bool = False,
                          *, scale: int = 1, fixed_scene: bool = False) -> QImage:
    """返回面板 QImage；默认保留真实屏幕定位，固定媒体场景隐藏窗口并在 2x 画布绘制。

    同意/否决按钮在 0.6 秒内是灰的，截图时按“已生效”画。
    """
    from shion.panel import ARM_DELAY, ConnectionPanel, InputPanel, PermissionPanel
    from shion.v3_window import V3PetWindow

    if fixed_scene and kind != "permission":
        raise ValueError("固定媒体场景仅支持授权面板")
    app = QApplication.instance() or QApplication(sys.argv)
    lines = Lines(lang)
    ui = lines.ui
    font_bubble = BubbleWindow()
    font_bubble.set_font_fallback(lines.font_fallback)
    family = font_bubble.font_family
    if fixed_scene:
        family = {"zh": "Microsoft YaHei UI", "en": "Cascadia Mono", "ja": "Yu Gothic UI"}[lang]
    body = (400, 400, 100, 100)
    scene_pet = None
    if (with_pet and kind != "eating") or kind == "budget":
        scene_pet = V3PetWindow(autostart=False, debug=False, **(
            {"height": 260, "clock": lambda: 100.0, "rng": random.Random(42), "pixel_ratio": scale}
            if fixed_scene else {}))
        if fixed_scene:
            scene_pet.setAttribute(Qt.WA_DontShowOnScreen)
        scene_pet.move(body[0] - MARGIN_X, body[1] - MARGIN_TOP)
        body = scene_pet.body_rect()
    if kind == "eating":
        from shion.effects import CrumbOverlay
        win = V3PetWindow(autostart=False, debug=False)
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
        mouth = win.mapFromGlobal(win.mouth_anchor())  # rig 嘴部
        p.drawImage(mouth.x() - panel.SIZE // 2, mouth.y() - 40, crumbs)
        p.end()
        win.close()
    elif kind == "budget":
        from shion.badge import CheckpointPanel, checkpoint_budget_texts
        from shion.remote import BudgetPause
        from shion.weekly_ui import ensure_fonts

        ensure_fonts()
        scene_pet.setAttribute(Qt.WA_DontShowOnScreen)
        scene_pet.show()
        panel = CheckpointPanel(scene_pet, lines.font_fallback)
        panel.setAttribute(Qt.WA_DontShowOnScreen)
        panel.present([("snapshot", "Claude Code")], {**checkpoint_budget_texts(lines), "end": ui("checkpoint_end")},
                      budgets={"snapshot": (BudgetPause(10_200_000, 10_000_000), False)})
        img = panel.grab().toImage()
    elif kind in ("dialogue", "snacks"):
        from shion.dialogue import DialoguePanel
        from shion.menu_content import MenuContent
        panel = DialoguePanel(MenuContent(), lines, family)
        panel.open(body)
        if kind == "snacks":
            panel._choose("page", "snacks")
        img = panel.grab().toImage()
    elif kind == "connection":
        from tools.hooks_config import user_settings_path
        panel = ConnectionPanel(family)
        path = str(user_settings_path()).replace("\\", "\\\u200b").replace("/", "/\u200b")
        panel.open({"title": ui("connection_title"), "body": ui("connection_explain", path=path),
                    "connect": ui("connection_accept"), "later": ui("connection_later")}, body)
        img = panel.grab().toImage()
    elif kind == "about":
        from PySide6.QtWidgets import QMessageBox
        from shion.windowing import position_dialog
        panel = QMessageBox()
        panel.setWindowTitle(ui("about_title"))
        panel.setText(ui("about_body", version=__version__))
        panel.setStandardButtons(QMessageBox.Ok)
        panel.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        panel.setAttribute(Qt.WA_ShowWithoutActivating)
        panel.show()
        position_dialog(panel, body)
        img = panel.grab().toImage()
    elif kind == "input":
        panel = InputPanel(family)
        panel.open(ui("panel_bad_title"), ui("panel_send"), ui("panel_cancel"), body)
        img = panel.grab().toImage()
    else:
        t = [0.0]
        panel = PermissionPanel(family, clock=lambda: t[0])
        if fixed_scene:
            panel.setAttribute(Qt.WA_DontShowOnScreen)
        panel.show_request(
            "snapshot", "Bash", text, more,
            {"title": ui("permission_title"), "allow": ui("permission_allow"), "deny": ui("permission_deny"),
             "more": ui("permission_more"), "expand": ui("permission_details"),
             "collapse": ui("permission_collapse"), "command_warning": ui("permission_command_warning")},
            body, summary=permission_summary("Bash", text, ui),
        )
        if expand:
            panel._toggle.click()
        t[0] += ARM_DELAY + 0.1
        panel.refresh_enabled()
        if fixed_scene:
            panel._timer.stop()
            panel.hide()
            panel.move(body[0] + body[2] + 16, body[1] + (body[3] - panel.height()) // 2)
            img = render_widget_image(panel, scale)
        else:
            img = panel.grab().toImage()
    if scene_pet is not None and with_pet:
        # 使用真实定位结果合成，能同时检查对话框与身体是否重叠。
        bounds = scene_pet.geometry().united(panel.geometry())
        canvas = QImage(bounds.size() * scale, QImage.Format_ARGB32_Premultiplied)
        canvas.setDevicePixelRatio(scale)
        canvas.fill(0)
        painter = QPainter(canvas)
        painter.drawImage(scene_pet.pos() - bounds.topLeft(), scene_pet.render_frame(scale))
        painter.drawImage(panel.pos() - bounds.topLeft(), img)
        painter.end()
        img = canvas
    font_bubble.close()
    font_bubble.deleteLater()
    panel.hide()
    panel.setParent(None)
    panel.deleteLater()  # 在这里（GUI 线程）立刻销毁，别留给别的线程里的垃圾回收
    if scene_pet is not None:
        scene_pet.close()
        scene_pet.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    del app
    return img


def snapshot_panel(out: str, kind: str, text: str = "git status", lang: str = "zh",
                   more: int = 0, expand: bool = False, with_pet: bool = False) -> int:
    """原面板截图入口，保留真实屏幕定位与 PNG 输出。"""
    img = render_snapshot_panel(kind, text, lang, more, expand, with_pet)
    ok = img.save(out, "PNG")
    if not ok:
        print(f"保存失败：{out}", file=sys.stderr)
        return 1
    print(f"saved {out} ({img.width()}x{img.height()})")
    return 0
