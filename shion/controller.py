"""控制器：把窗口的手势信号接到状态机，再把状态机的结果同步回窗口。

窗口只管“看到什么”，状态机只管“发生了什么”，这里是中间人。
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta
from typing import Callable, Optional

from PySide6.QtCore import QObject, QPoint, QTimer, Qt, Signal
from PySide6.QtGui import QActionGroup, QCursor, QGuiApplication
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox

from shion.activity import ActivityLog, describe, make_entry, parse_working
from shion.bubble import BubbleWindow
from shion.behavior import IDLE_EXPRESSIONS, IDLE_EXPRESSION_WEIGHTS, IdleBehavior
from shion.effects import HeartOverlay
from shion.lines import Lines
from shion.panel import InputPanel
from shion.remote import RemoteHub
from shion.pet_window import PetWindow
from shion.speech import PatSession, Priority, SpeechGate, speech_kind
from shion.state import ACTIVITY_LEVELS, EXPRESSIONS, PetState, Reaction, SaveScheduler

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
ACTIVITY_REPEAT = timedelta(seconds=3)  # 同一句“在干什么”这么久内不重复弹


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
        hub: Optional[RemoteHub] = None,
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
        self.hub = hub or RemoteHub()
        self._pause_timed_out = False
        self._input_panel: Optional[InputPanel] = None
        self._now_fn = now_fn
        self._say_fn = say or self._bubble_say
        self._pat_session = PatSession()
        self._speech = SpeechGate()
        self._rng = random.Random()
        self._idle = IdleBehavior()
        self._menu_open = False
        self.activity = ActivityLog()
        self._last_activity_say: Optional[tuple[str, datetime]] = None

        # 双击显示状态：等一个双击间隔，期间没有新的点击才显示
        self.status_delay_ms = QApplication.doubleClickInterval() if QApplication.instance() else 500
        self._status_timer = QTimer(self)
        self._status_timer.setTimerType(Qt.PreciseTimer)
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
        w.pressed.connect(self._on_pressed)
        w.motion_finished.connect(self.save_position)

        self._watch_screens()

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
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
        now = self._now()
        cur = self.state.current(now)
        calm = (
            self.state.is_working(now) or bool(self.state.save.fixed_expression)
            or cur == "sleep" or self.state.save.activity_level == "quiet"
        )
        self.window.set_calm(calm)
        if calm and self.window.idle_motion_active:
            self.window.stop_motion()
        if cur != self.window.sprite_name:
            self.window.set_state(cur)

    def tick(self) -> None:
        now = self._now()
        self._sync_pause()
        self.react(self.state.tick(now))
        self.sync()
        action = self._idle.step(
            self.window.monotonic_time(), self.state.can_idle(now)
            and not self.window.motion_active and not self.window.is_falling
            and not self.window.is_pressed and not self._menu_open,
            self.state.save.activity_level,
        )
        if action == "turn":
            self.window.turn()
        elif action == "face":
            self.window.face(1 if QCursor.pos().x() >= self.window.geometry().center().x() else -1)
        elif action == "jump":
            self.window.jump(automatic=True)
        elif action == "expression":
            self.state.idle_expression(
                self._rng.choices(IDLE_EXPRESSIONS, weights=IDLE_EXPRESSION_WEIGHTS, k=1)[0], now
            )
            self.sync()
        elif action == "talk":
            self.say_key("idle_talk")
        self.scheduler.poll(now)

    def react(self, reactions: list[Reaction], *, category: str | None = None) -> None:
        for r in reactions:
            if r.kind == "say":
                self.say_key(r.key, category=category)
            elif r.kind == "nudge":
                if (not self.state.save.fixed_expression and not self.state.is_working(self._now())
                        and self.state.current(self._now()) != "sleep"
                        and self.state.save.activity_level != "quiet"):
                    self.window.bounce()

    def say_key(self, key: str, *, category: str | None = None) -> bool:
        if self.state.save.bubble_muted:
            return False
        priority, default_category = speech_kind(key)
        category = category if priority == Priority.LOW and category else default_category
        if not self._speech.allows(self.window.monotonic_time(), priority, category):
            return False
        text = self.lines.pick(key)
        return self.say(text, priority=priority, category=category) if text else False

    def greet_startup(self, first_start: bool, from_hook: bool = False) -> None:
        """首次介绍自己；普通重启用 startup，hook 拉起留给 session_start 问候。"""
        if first_start or not from_hook:
            self.say_key("intro" if first_start else "startup")

    def say_text(self, text: str, *, priority: Priority = Priority.LOW,
                 category: str = "claude_working") -> bool:
        """说一句现成的文字（遵守静音）。"""
        if not self.state.save.bubble_muted:
            return self.say(text, priority=priority, category=category)
        return False

    def say(self, text: str, *, priority: Priority = Priority.MEDIUM,
            category: str = "status", sticky: bool = False) -> bool:
        if not self._speech.start(self.window.monotonic_time(), text, priority, category, sticky):
            return False
        log.info("说：%s", text)
        if sticky:
            self._say_fn(text, sticky=True)
        else:
            self._say_fn(text)
        return True

    def _bubble_say(self, text: str, sticky: bool = False) -> None:
        if self.bubble is None:
            return
        self.bubble.follow(self.window.body_rect())
        if sticky:
            self.bubble.say(text, sticky=True)
        else:
            self.bubble.say(text)

    def _on_window_moved(self) -> None:
        if self.bubble is not None and self.bubble.isVisible():
            self.bubble.follow(self.window.body_rect())

    # ------------------------------------------------------------ 手势
    def _on_pressed(self) -> None:
        self._idle.next_at = None

    def _on_hover(self) -> None:
        self.react(self.state.interact(self._now()))
        self.sync()

    def _on_pat(self) -> None:
        self.window.stop_motion()
        self._on_pressed()
        self._status_timer.stop()
        reactions = self.state.pat(self._now())
        due = self._pat_session.feed(self.window.monotonic_time())
        if not reactions and due:
            reactions = [Reaction("say", "pat")]
        self.react(reactions, category="pat")
        if self.overlay is not None:
            self.overlay.burst(self.window.head_anchor(), start_session=self._pat_session.new_session)
        self.sync()

    def _on_click(self) -> None:
        self.window.stop_motion()
        self._on_pressed()
        self._status_timer.stop()
        self.react(self.state.click(self._now()), category="poke")
        self.sync()

    def _on_double_click(self) -> None:
        self.react(self.state.interact(self._now()))
        self._status_timer.start(self.status_delay_ms)
        self.sync()

    def _on_drag_started(self) -> None:
        self.window.stop_motion()
        self._on_pressed()
        self._status_timer.stop()
        self.react(self.state.drag_start(self._now()), category="drag")
        self.sync()

    def _on_drag_finished(self) -> None:
        self.react(self.state.drag_end(self._now(), shaken=self.window.consume_shaken()), category="drag")
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
        self.window.stop_motion()
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
        self._speech.dismiss()
        if self.bubble is not None:
            self.bubble.set_font_fallback(self.lines.font_fallback)
            self.bubble.dismiss()
        self.scheduler.mark_dirty(self._now())

    def set_privacy(self, private: bool) -> None:
        self.state.save.privacy_mode = private
        self.activity.clear()  # 之前记下的文件名等不会在切换后冒出来
        self.scheduler.mark_dirty(self._now())

    def set_muted(self, muted: bool) -> None:
        self.state.save.bubble_muted = muted
        if muted:
            self._speech.dismiss()
        if muted and self.bubble is not None:
            self.bubble.dismiss()
        self.scheduler.mark_dirty(self._now())

    def select_expression(self, name: str) -> None:
        self.window.stop_motion()
        self.state.select_expression(name, self._now())
        self.sync()

    def fix_expression(self, fixed: bool) -> None:
        self.window.stop_motion()
        self.state.fix_expression(fixed, self._now())
        self.sync()

    def set_activity(self, level: str) -> None:
        if level not in ACTIVITY_LEVELS:
            return
        self.state.save.activity_level = level
        self._idle.next_at = None
        self.scheduler.mark_dirty(self._now())
        self.sync()

    def do_action(self, name: str) -> None:
        self.react(self.state.interact(self._now()))
        self._idle.next_at = None
        if name in ("walk", "cross"):
            self.window.walk(cross=name == "cross", rng=self._rng)
        elif name == "jump":
            self.window.jump()
        elif name == "turn":
            self.window.turn()
        self.sync()

    # ------------------------------------------------------------ 来自 Claude 的事件
    def handle_event(self, etype: str, detail: Optional[str] = None) -> None:
        """处理本地 HTTP 服务转来的事件（必须在 GUI 线程调用，见 bridge.py）。"""
        private = self.state.save.privacy_mode
        log.info("收到事件：%s %r", etype, None if private else detail)
        now = self._now()
        if etype == "pause_timeout":
            self._on_pause_timeout()
            return
        if etype == "prompt":
            self._sync_pause()  # 服务线程已经在 hub 里解除了暂停
        ui = self.lines.ui
        entry = make_entry(etype, detail, now)
        self.activity.add(entry)
        reactions = self.state.claude_event(etype, detail, now)
        greeted = any(r.key in ("wake", "neglect_return") for r in reactions)  # 这句别被盖掉
        if etype == "working" and parse_working(detail):
            # 用“在读 x.py……”代替随机的“Claude 在努力中”
            reactions = [r for r in reactions if r.key != "claude_working"]
            self.react(reactions)
            if not greeted:
                self._say_activity(describe(entry, ui, private), now)
        elif etype == "stop" and entry is not None and entry.target and not private:
            reactions = [r for r in reactions if r.key != "claude_done"]
            self.react(reactions)
            self.say_text(ui("done_summary", text=entry.target),
                          priority=Priority.HIGH, category="claude_done")
        else:
            self.react(reactions)
        self.sync()

    def _say_activity(self, text: str, now: datetime) -> None:
        last = self._last_activity_say
        if last and last[0] == text and now - last[1] < ACTIVITY_REPEAT:
            return
        if self.say_text(text):
            self._last_activity_say = (text, now)

    # ------------------------------------------------------------ 遥控：暂停 / 反馈
    def pause_work(self) -> None:
        """下一次工具调用前让 Claude 停住（hook 在 hub 上等待）。"""
        self.react(self.state.interact(self._now()))
        self._pause_timed_out = False
        self.hub.pause()
        self.state.paused = True
        self._speech.dismiss()
        self.refresh_pause_bubble()
        self.sync()

    def resume_work(self, *, quiet: bool = False) -> None:
        self.hub.resume()
        self._leave_pause()
        if not quiet:
            self.say_key("resumed")
        self.sync()

    def _leave_pause(self) -> None:
        was_sticky = self._speech.sticky
        self.state.paused = False
        self._pause_timed_out = False
        if was_sticky:
            self._speech.dismiss()
            if self.bubble is not None:
                self.bubble.dismiss()

    def _sync_pause(self) -> None:
        """hub 在服务线程里被解除暂停（用户在 CC 里说话）后，把界面状态同步过来。"""
        if self.state.paused and not self.hub.is_paused:
            self._leave_pause()
        self.refresh_pause_bubble()

    def _on_pause_timeout(self) -> None:
        """hook 等满时限后已拒绝工具调用：保持暂停标记，提示用户去 CC 里说话。"""
        if not self.state.paused:
            return
        self._pause_timed_out = True
        self._speech.dismiss()
        self.refresh_pause_bubble()

    def refresh_pause_bubble(self) -> None:
        """暂停期间让“暂停中”一直挂着；被别的台词盖掉后，等那句说完再恢复。"""
        if not self.state.paused or self.state.save.bubble_muted:
            return
        if self.window.monotonic_time() < self._speech.until:
            return
        key = "paused_timeout" if self._pause_timed_out else "paused_status"
        self.say(self.lines.ui(key), priority=Priority.MEDIUM, category="paused", sticky=True)

    def feedback_good(self) -> None:
        self.react(self.state.feedback_good(self._now()))
        self.sync()

    def open_bad_feedback(self) -> None:
        """“有问题……”：弹出一行输入框，发送后加入反馈队列。"""
        self.window.stop_motion()
        if self._input_panel is None:
            family = self.bubble.font_family if self.bubble is not None else "Consolas"
            self._input_panel = InputPanel(family)
            self._input_panel.submitted.connect(self.feedback_bad)
        ui = self.lines.ui
        self._input_panel.open(
            ui("panel_bad_title"), ui("panel_send"), ui("panel_cancel"), self.window.body_rect()
        )

    def feedback_bad(self, text: str = "") -> None:
        self.react(self.state.feedback_bad(text, self._now()))
        self.sync()

    def take_feedback_text(self) -> str:
        """取走反馈队列，合成要注入给 Claude 的文字（给 /feedback/take 用）；没有就返回空串。"""
        items = self.state.take_feedback(self._now())
        log.info("取走反馈：%d 条", len(items))
        if not items:
            return ""
        ui = self.lines.ui
        parts = []
        if any(i["kind"] == "good" for i in items):
            parts.append(ui("hook_praise"))
        for i in items:
            if i["kind"] == "bad":
                parts.append(ui("hook_bad", text=i["text"]) if i["text"] else ui("hook_bad_plain"))
        if not self.state.save.inject_praise:
            return ""
        self.say_key("feedback_sent")
        return "\n".join(parts)

    def quit(self) -> None:
        self.window.stop_motion()
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
        text = ui(
            "status", span=span, pats=save.stats["pats"],
            tasks=save.stats["claude_tasks"], affection=save.affection,
        )
        if save.fixed_expression:
            text += "\n" + ui("expression_fixed")
        return text

    def _show_status(self) -> None:
        text = self.status_text()
        recent = self.activity.recent_lines(self.lines.ui, self.state.save.privacy_mode)
        if recent:
            text += "\n" + self.lines.ui("recent_header") + "\n" + "\n".join(recent)
        self.say(text)

    # ------------------------------------------------------------ 菜单
    def build_menu(self) -> QMenu:
        menu = QMenu()
        ui = self.lines.ui
        remote_menu = menu.addMenu(ui("menu_remote"))
        if self.state.paused:
            remote_menu.addAction(ui("menu_resume")).triggered.connect(lambda: self.resume_work())
        else:
            remote_menu.addAction(ui("menu_pause")).triggered.connect(self.pause_work)
        remote_menu.addAction(ui("menu_good")).triggered.connect(self.feedback_good)
        remote_menu.addAction(ui("menu_bad")).triggered.connect(self.open_bad_feedback)

        expression_menu = menu.addMenu(ui("menu_expression"))
        expression_group = QActionGroup(expression_menu)
        expression_group.setExclusive(True)
        cur_expression = self.state.current(self._now())
        for name in EXPRESSIONS:
            act = expression_menu.addAction(ui("expression_" + name))
            act.setCheckable(True)
            act.setChecked(name == cur_expression)
            expression_group.addAction(act)
            act.triggered.connect(lambda _=False, n=name: self.select_expression(n))
        expression_menu.addSeparator()
        fixed = expression_menu.addAction(ui("menu_fix_expression"))
        fixed.setCheckable(True)
        fixed.setChecked(bool(self.state.save.fixed_expression))
        fixed.triggered.connect(self.fix_expression)
        expression_menu.addAction(ui("menu_auto_expression")).triggered.connect(lambda: self.fix_expression(False))

        activity_menu = menu.addMenu(ui("menu_activity"))
        activity_group = QActionGroup(activity_menu)
        activity_group.setExclusive(True)
        for level in ACTIVITY_LEVELS:
            act = activity_menu.addAction(ui("activity_" + level))
            act.setCheckable(True)
            act.setChecked(level == self.state.save.activity_level)
            activity_group.addAction(act)
            act.triggered.connect(lambda _=False, lv=level: self.set_activity(lv))

        action_menu = menu.addMenu(ui("menu_action"))
        for name in ("walk", "cross", "jump", "turn"):
            action_menu.addAction(ui("action_" + name)).triggered.connect(lambda _=False, n=name: self.do_action(n))

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

        privacy = menu.addAction(ui("menu_privacy"))
        privacy.setCheckable(True)
        privacy.setChecked(self.state.save.privacy_mode)
        privacy.triggered.connect(self.set_privacy)

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
        self.window.stop_motion()
        self._idle.next_at = None
        self.react(self.state.interact(self._now()))
        self.sync()
        menu = self.build_menu()
        self._menu_open = True
        try:
            menu.exec(pos)
        finally:
            self._menu_open = False
            menu.deleteLater()

    def show_about(self) -> None:
        QMessageBox.about(
            self.window,
            self.lines.ui("about_title"),
            self.lines.ui("about_body", version=VERSION),
        )
