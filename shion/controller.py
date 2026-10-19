"""控制器：把窗口的手势信号接到状态机，再把状态机的结果同步回窗口。

窗口只管“看到什么”，状态机只管“发生了什么”，这里是中间人。
"""
from __future__ import annotations

import logging
import random
from datetime import datetime
from typing import Callable, Optional

from PySide6.QtCore import QObject, QPoint, QTimer, Signal
from PySide6.QtGui import QActionGroup, QGuiApplication
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox

from shion.bubble import BubbleWindow
from shion.effects import HeartOverlay
from shion.lines import Lines
from shion.pet_window import PetWindow
from shion.state import PetState, Reaction, SaveScheduler

log = logging.getLogger("shion.controller")

SIZES = (160, 200, 260, 320)


def pick_screen_rect(rects, x, y, w, h):
    """按存档里的窗口位置 (x, y, w, h) 选该放在哪块屏上，返回那块屏的可用区域；都不匹配返回 None。

    优先包含窗口中心点的屏；没有 y（旧存档）或没找到，就看哪块屏的横向范围包含窗口中心 x。
    """
    cx = x + w // 2
    if y is not None:
        cy = y + h // 2
        for r in rects:
            rx, ry, rw, rh = r
            if rx <= cx < rx + rw and ry <= cy < ry + rh:
                return r
    for r in rects:
        rx, _, rw, _ = r
        if rx <= cx < rx + rw:
            return r
    return None
VERSION = "0.1"
TICK_MS = 100
PAT_SAY_EVERY = 4  # 摸头每 4 次说一句话


class PetController(QObject):
    quit_requested = Signal()

    def __init__(
        self,
        window: PetWindow,
        state: PetState,
        scheduler: SaveScheduler,
        lines: Optional[Lines] = None,
        overlay: Optional[HeartOverlay] = None,
        bubble: Optional[BubbleWindow] = None,
        now_fn: Callable[[], datetime] = datetime.now,
        say: Optional[Callable[[str], None]] = None,
        autostart: bool = True,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.window = window
        self.state = state
        self.scheduler = scheduler
        self.lines = lines or Lines()
        self.overlay = overlay
        self.bubble = bubble
        self._now_fn = now_fn
        self._say_fn = say or self._bubble_say
        self._pat_count = 0
        self._rng = random.Random()

        # 双击显示状态：等一个双击间隔，期间没有新的点击才显示
        self.status_delay_ms = QApplication.doubleClickInterval() if QApplication.instance() else 500
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(self._show_status)

        w = window
        w.hovered.connect(self._on_hover)
        w.patted.connect(self._on_pat)
        w.clicked.connect(self._on_click)
        w.double_clicked.connect(self._on_double_click)
        w.drag_started.connect(self._on_drag_started)
        w.drag_finished.connect(self._on_drag_finished)
        w.menu_requested.connect(self.show_menu)
        w.moved.connect(self._on_window_moved)

        self._watch_screens()

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self.tick)
        self.sync()
        if autostart:
            self._timer.start()

    # ------------------------------------------------------------ 基础
    def _now(self) -> datetime:
        return self._now_fn()

    def sync(self) -> None:
        """把状态机当前应显示的精灵同步给窗口（只在变化时切换，不打断呼吸相位）。"""
        cur = self.state.current(self._now())
        if cur != self.window.sprite_name:
            self.window.set_state(cur)

    def tick(self) -> None:
        now = self._now()
        self.state.tick(now)
        self.sync()
        self.scheduler.poll(now)

    def react(self, reactions: list[Reaction]) -> None:
        for r in reactions:
            if r.kind == "say":
                self.say_key(r.key)

    def say_key(self, key: str) -> None:
        if self.state.save.bubble_muted:
            return
        text = self.lines.pick(key)
        if text:
            self.say(text)

    def say(self, text: str) -> None:
        log.info("说：%s", text)
        self._say_fn(text)

    def _bubble_say(self, text: str) -> None:
        if self.bubble is None:
            return
        self.bubble.follow(self.window.body_rect())
        self.bubble.say(text)

    def _on_window_moved(self) -> None:
        if self.bubble is not None and self.bubble.isVisible():
            self.bubble.follow(self.window.body_rect())

    # ------------------------------------------------------------ 手势
    def _on_hover(self) -> None:
        self.react(self.state.interact(self._now()))
        self.sync()

    def _on_pat(self) -> None:
        self._status_timer.stop()
        reactions = self.state.pat(self._now())
        self._pat_count += 1
        if not reactions and self._pat_count % PAT_SAY_EVERY == 1:
            reactions = [Reaction("say", "pat")]
        self.react(reactions)
        if self.overlay is not None:
            self.overlay.burst(self.window.head_anchor(), self._rng.choice((1, 2)))
        self.sync()

    def _on_click(self) -> None:
        self._status_timer.stop()
        self.react(self.state.click(self._now()))
        self.sync()

    def _on_double_click(self) -> None:
        self.react(self.state.interact(self._now()))
        self._status_timer.start(self.status_delay_ms)
        self.sync()

    def _on_drag_started(self) -> None:
        self._status_timer.stop()
        self.react(self.state.drag_start(self._now()))
        self.sync()

    def _on_drag_finished(self) -> None:
        self.react(self.state.drag_end(self._now()))
        self.save_position()
        self.sync()

    # ------------------------------------------------------------ 存档 / 位置
    def save_position(self) -> None:
        self.state.save.window["x"] = self.window.x()
        self.state.save.window["y"] = self.window.y()
        self.scheduler.mark_dirty(self._now())

    def _screen_rects(self):
        out = []
        for screen in QGuiApplication.screens():
            g = screen.availableGeometry()
            out.append((g.x(), g.y(), g.width(), g.height()))
        return out

    def restore_position(self) -> None:
        """按存档恢复位置：放回原来那块屏、脚底贴它的底边；找不到就用默认右下角。"""
        save = self.state.save.window
        x, y = save.get("x"), save.get("y")
        if isinstance(x, int):
            rect = pick_screen_rect(
                self._screen_rects(), x, y if isinstance(y, int) else None,
                self.window.width(), self.window.height(),
            )
            if rect is not None:
                self.window.place_on(rect, x)
                return
        self.window.place_default()

    # ---- 屏幕变化（分辨率、任务栏、拔插副屏）----
    def _watch_screens(self) -> None:
        app = QGuiApplication.instance()
        if app is None:
            return
        for screen in QGuiApplication.screens():
            screen.availableGeometryChanged.connect(self.relocate)
        app.screenAdded.connect(self._on_screen_added)
        app.screenRemoved.connect(self.relocate)

    def _on_screen_added(self, screen) -> None:
        screen.availableGeometryChanged.connect(self.relocate)
        self.relocate()

    def relocate(self, *_args) -> None:
        """窗口跑出所有屏幕就回默认位置，否则重新贴底。拖动/下落中不动。"""
        if self.window.is_dragging or self.window.is_falling:
            return
        x, y, w, h = self.window.body_rect()
        cx, cy = x + w // 2, y + h // 2
        if any(rx <= cx < rx + rw and ry <= cy < ry + rh for rx, ry, rw, rh in self._screen_rects()):
            self.window.snap_to_floor()
        else:
            self.window.place_default()

    def set_size(self, height: int) -> None:
        self.window.set_height(height)
        self.window.snap_to_floor()
        self.state.save.window["height"] = height
        self.save_position()
        self.sync()

    def set_language(self, code: str) -> None:
        """切换语言，立即生效并存档：之后的台词、菜单、状态文字都用新语言，旧气泡收起。"""
        self.lines.set_language(code)
        self.state.save.language = self.lines.lang
        if self.bubble is not None:
            self.bubble.set_font_fallback(self.lines.font_fallback)
            self.bubble.dismiss()
        self.scheduler.mark_dirty(self._now())

    def set_muted(self, muted: bool) -> None:
        self.state.save.bubble_muted = muted
        if muted and self.bubble is not None:
            self.bubble.dismiss()
        self.scheduler.mark_dirty(self._now())

    # ------------------------------------------------------------ 来自 Claude 的事件
    def handle_event(self, etype: str, detail: Optional[str] = None) -> None:
        """处理本地 HTTP 服务转来的事件（必须在 GUI 线程调用，见 bridge.py）。"""
        self.react(self.state.claude_event(etype, detail, self._now()))
        self.sync()

    def take_praise(self) -> int:
        """取走待夸奖计数（给 /praise/take 用）。"""
        return self.state.take_praise(self._now())

    def praise(self) -> None:
        self.react(self.state.praise_claude(self._now()))
        self.sync()

    def quit(self) -> None:
        try:
            self.scheduler.flush()  # 内部不抛异常；这里再兜一层，保证一定能退出
        except Exception:
            log.exception("退出时写存档失败")
        finally:
            self.quit_requested.emit()

    # ------------------------------------------------------------ 双击状态
    def status_text(self, now: Optional[datetime] = None) -> str:
        now = now or self._now()
        save = self.state.save
        together = now - (save.first_run or now)
        days, hours = together.days, together.seconds // 3600
        ui = self.lines.ui
        if days:
            span = ui("span_days", days=days, hours=hours)
        elif hours:
            span = ui("span_hours", hours=hours, minutes=together.seconds % 3600 // 60)
        else:
            span = ui("span_minutes", minutes=together.seconds // 60)
        return ui(
            "status", span=span, pats=save.stats["pats"],
            tasks=save.stats["claude_tasks"], affection=save.affection,
        )

    def _show_status(self) -> None:
        self.say(self.status_text())

    # ------------------------------------------------------------ 菜单
    def build_menu(self) -> QMenu:
        menu = QMenu()
        ui = self.lines.ui
        menu.addAction(ui("menu_praise")).triggered.connect(self.praise)

        size_menu = menu.addMenu(ui("menu_size"))
        group = QActionGroup(size_menu)
        group.setExclusive(True)
        cur = self.state.save.window.get("height", 200)
        for h in SIZES:
            act = size_menu.addAction(str(h))
            act.setCheckable(True)
            act.setChecked(h == cur)
            group.addAction(act)
            act.triggered.connect(lambda _=False, h=h: self.set_size(h))

        mute = menu.addAction(ui("menu_mute"))
        mute.setCheckable(True)
        mute.setChecked(self.state.save.bubble_muted)
        mute.triggered.connect(self.set_muted)

        lang_menu = menu.addMenu(ui("menu_language"))
        lang_group = QActionGroup(lang_menu)
        lang_group.setExclusive(True)
        for code, name in self.lines.available_languages():
            act = lang_menu.addAction(name)
            act.setCheckable(True)
            act.setChecked(code == self.lines.lang)
            lang_group.addAction(act)
            act.triggered.connect(lambda _=False, c=code: self.set_language(c))

        auto = menu.addAction(ui("menu_autostart"))
        auto.setEnabled(False)

        menu.addSeparator()
        menu.addAction(ui("menu_about")).triggered.connect(self.show_about)
        menu.addAction(ui("menu_quit")).triggered.connect(self.quit)
        return menu

    def show_menu(self, pos: QPoint) -> None:
        self.react(self.state.interact(self._now()))
        self.sync()
        menu = self.build_menu()
        menu.exec(pos)
        menu.deleteLater()

    def show_about(self) -> None:
        QMessageBox.about(
            self.window,
            self.lines.ui("about_title"),
            self.lines.ui("about_body", version=VERSION),
        )
