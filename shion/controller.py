"""控制器：把窗口的手势信号接到状态机，再把状态机的结果同步回窗口。

窗口只管“看到什么”，状态机只管“发生了什么”，这里是中间人。
"""
from __future__ import annotations

import json
import logging
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, QProcess, QRect, QTimer, Qt, Signal
from PySide6.QtGui import QActionGroup, QCursor, QGuiApplication
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox

from shion import __version__
from shion.windowing import position_dialog, raise_without_activation, set_topmost
from shion.foreground import ForegroundFollower

from shion.activity import ActivityLog, describe, make_entry, parse_working
from shion.bubble import BubbleWindow
from shion.behavior import IDLE_EXPRESSIONS, IDLE_EXPRESSION_WEIGHTS, IdleBehavior, NEGLECT_DESK_CHANCE
from shion.effects import HeartOverlay, CrumbOverlay, MOUTH_FRACTION
from shion.dialogue import DialoguePanel
from shion.menu_content import MenuContent, localized
from shion.lines import Lines
from shion import interrupt
from shion.panel import InputPanel, PermissionPanel
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
TICK_MS = 100
ACTIVITY_REPEAT = timedelta(seconds=3)  # 同一句“在干什么”这么久内不重复弹
ROOT = Path(__file__).resolve().parent.parent
CONTINUE_SEND_TIMEOUT_MS = 10_000


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
        self._held_said = False  # 这次停下已经说过“已经停下啦～”
        self._held_seen = False  # 这次停下 hook 已经真的在检查点停住过（显示标签，直到继续）
        self._procs: dict[str, interrupt.CCProcess] = {}  # 会话 → hook 报来的 CC 进程（立即中断用）
        self._tool_wall: dict[str, dict[str, float]] = {}  # 会话 → {tool_use_id: 开始的 Unix 秒}
        self._interrupted: set[str] = set()  # 被立即中断、还没重新开始的会话
        self._end_pending: set[str] = set()  # 这一轮被诗音结束了（中断 / 停下拿到 stop / 停太久）：紧接着的 Stop 不算完成
        # 最近一个被诗音结束了这一轮（立即中断 / 停太久）的会话：(会话, CC 进程或 None)，菜单上可以“继续”
        self._ended: Optional[tuple[str, Optional[interrupt.CCProcess]]] = None
        self._continue_sending = False
        self.continue_runner: Callable[[interrupt.CCProcess, str, Callable[[dict], None]], None] =             self._run_console_send
        self.process_view = interrupt.ProcessView()
        self.hook_images: tuple[str, ...] = (str(ROOT / ".venv" / "Scripts" / "python.exe"),)
        self._input_panel: Optional[InputPanel] = None
        self._perm_panel: Optional[PermissionPanel] = None
        self._dialogue: Optional[DialoguePanel] = None
        self._crumbs: Optional[CrumbOverlay] = None
        self._about: Optional[QMessageBox] = None
        self.menu_content = MenuContent()
        self._autostart = autostart
        self._now_fn = now_fn
        self._say_fn = say or self._bubble_say
        self._pat_session = PatSession()
        self._speech = SpeechGate()
        self._rng = random.Random()
        self._idle = IdleBehavior()
        self._menu_open = False
        self._neglect_checked = False
        self._last_rare_idle = -float("inf")
        window.release_to_taskbar = state.save.release_to_taskbar
        self.activity = ActivityLog()
        self._last_activity_say: Optional[tuple[str, datetime]] = None

        # 双击显示状态：等一个双击间隔，期间没有新的点击才显示
        self.status_delay_ms = QApplication.doubleClickInterval() if QApplication.instance() else 500
        self._status_timer = QTimer(self)
        self._status_timer.setTimerType(Qt.PreciseTimer)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(self._show_status)

        w = window
        w.patted.connect(self._on_pat)
        w.gesture.connect(self._on_gesture)
        w.clicked.connect(self._on_click)
        w.double_clicked.connect(self._on_double_click)
        w.drag_started.connect(self._on_drag_started)
        w.drag_finished.connect(self._on_drag_finished)
        w.menu_requested.connect(self.show_menu)
        w.moved.connect(self._on_window_moved)
        w.pressed.connect(self._on_pressed)
        w.resume_requested.connect(self.resume_work)

        self._watch_screens()

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self.tick)
        self._foreground = ForegroundFollower(self._pet_windows, parent=self)
        self._apply_topmost()
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
        if cur == "neglect1" and not self._neglect_checked:
            self._neglect_checked = True
            if self._rng.random() < NEGLECT_DESK_CHANCE:
                self.state.rest_at_desk(now, automatic=True)
                cur = self.state.current(now)
        elif cur not in ("neglect1", "desk"):
            self._neglect_checked = False
        calm = (
            self.state.is_working(now) or bool(self.state.save.fixed_expression)
            or cur in ("sleep", "desk") or self.state.save.activity_level == "quiet"
        )
        self.window.set_calm(calm)
        self.window.set_activity(self.state.save.activity_level)
        self.window.set_paused_badge(self.state.paused and self._held_seen,
                                     text=self.lines.ui("pause_label"), tooltip=self.lines.ui("pause_label_hint"),
                                     fallback=self.lines.font_fallback)
        if calm and self.window.idle_motion_active:
            self.window.stop_motion()
        if cur == "sleep" and self.state.sleep_in_bed(now):
            cur = "bed"
        if cur != self.window.sprite_name:
            self.window.set_state(cur)

    def tick(self) -> None:
        now = self._now()
        self._sync_pause()
        self._sync_permission()
        self.react(self.state.tick(now))
        self.sync()
        action = self._idle.step(
            self.window.monotonic_time(), self.state.can_idle(now)
            and not self.window.motion_active and not self.window.is_falling
            and not self.window.is_pressed and not self._menu_open
            and not (self._dialogue is not None and self._dialogue.isVisible()),
            self.state.save.activity_level,
        )
        if action == "turn":
            self.window.turn(automatic=True)
        elif action == "face":
            self.window.face(1 if QCursor.pos().x() >= self.window.geometry().center().x() else -1,
                             automatic=True)
        elif action == "jump":
            self.window.jump(automatic=True)
        elif action == "expression":
            self.state.idle_expression(
                self._rng.choices(IDLE_EXPRESSIONS, weights=IDLE_EXPRESSION_WEIGHTS, k=1)[0], now
            )
            self.sync()
        elif action == "talk":
            if not self._try_time_speech():
                self.say_key("idle_talk")
        self.scheduler.poll(now)
        if self._crumbs is not None and self._crumbs.isVisible():
            self._crumbs.follow(self._mouth_anchor())
        if self._dialogue is not None and self._dialogue.isVisible() and (
                self._dialogue.busy != self.state.eating or self._dialogue.level != self.state.affection_level):
            self._dialogue.busy = self.state.eating
            self._dialogue.level = self.state.affection_level
            self._dialogue.refresh()

    def react(self, reactions: list[Reaction], *, category: str | None = None) -> None:
        # 同一个 tick 也可能有催回提醒；升级放在本批最后，避免刚说出口就被盖掉。
        for r in sorted(reactions, key=lambda item: item.kind == "level_up"):
            if r.kind == "say":
                self.say_key(r.key, category=category)
            elif r.kind == "level_up" and self.state.affection is not None:
                item = self.state.affection.levels[int(r.key) - 1]
                self.say_text(localized(item.upgrade, self.lines.lang), priority=Priority.HIGH, category="level_up")
                if self.overlay is not None:
                    self.overlay.celebrate(self.window.head_anchor())
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
        level, rules = self.state.affection_level, self.state.affection
        rare = False
        if level is not None and key == "idle_talk" and level == len(rules.levels):
            now = self.window.monotonic_time()
            rare = now - self._last_rare_idle >= rules.rare_cooldown and self._rng.random() < rules.rare_chance
        text = self.lines.pick("idle_thanks", level) if rare else None
        if not text:
            rare = False
            text = self.lines.pick_for_level(key, level)
        accepted = self.say(text, priority=priority, category=category) if text else False
        if rare and accepted:
            self._last_rare_idle = self.window.monotonic_time()
        return accepted

    def _try_time_speech(self) -> bool:
        """只在明确的启动/交互/闲聊机会调用，不由 tick 自动补播。"""
        now = self._now()
        key = self.state.pending_time_speech(now)
        if key is not None and self.say_key(key):
            self.state.mark_time_speech_spoken(key, now)
            return True
        return False

    def greet_startup(self, first_start: bool, from_hook: bool = False) -> None:
        """首次介绍自己；普通重启用 startup，hook 拉起留给 session_start 问候。"""
        if first_start or not from_hook:
            self.say_key("intro" if first_start else "startup")
        self.react(self.state.gain_affection("open", self._now()))
        self._try_time_speech()

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
        if self._perm_panel is not None and self._perm_panel.isVisible():
            self._perm_panel.follow(self.window.body_rect())
        if self._dialogue is not None and self._dialogue.isVisible():
            self._dialogue.follow(self.window.body_rect())
        if self._crumbs is not None and self._crumbs.isVisible():
            self._crumbs.follow(self._mouth_anchor())

    # ------------------------------------------------------------ 手势
    def _on_pressed(self) -> None:
        self._idle.next_at = None

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
        self._try_time_speech()

    def _on_click(self) -> None:
        self.window.stop_motion()
        self._on_pressed()
        self._status_timer.stop()
        self.react(self.state.click(self._now()), category="poke")
        self.sync()
        self._try_time_speech()

    def _on_gesture(self, key: str) -> None:
        self._on_pressed()
        self._status_timer.stop()
        self.react(self.state.gesture(key, self._now()))
        self.sync()
        self._try_time_speech()

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
        self._try_time_speech()

    def _on_drag_finished(self) -> None:
        self.react(self.state.drag_end(self._now(), shaken=self.window.consume_shaken()), category="drag")
        self.save_position()
        self.sync()
        self._try_time_speech()

    # ------------------------------------------------------------ 存档 / 位置
    def save_position(self) -> None:
        # 存成普通画布的左边缘，重启/宽画布切换后脚底中心仍一致。
        self.state.save.window["x"] = round(self.window.x() + (self.window.sprite_size[0] - self.window.normal_width) / 2)
        self.state.save.window["y"] = self.window.y()
        self.scheduler.mark_dirty(self._now())

    def _screen_rects(self):
        out = []
        for screen in QGuiApplication.screens():
            g = screen.availableGeometry()
            out.append((g.x(), g.y(), g.width(), g.height()))
        return out

    def restore_position(self) -> None:
        """按存档恢复原屏和悬空位置；旧档无 y 时贴底，原屏移除时回默认右下角。"""
        save = self.state.save.window
        x, y = save.get("x"), save.get("y")
        if isinstance(x, int):
            rect = pick_screen_rect(
                self._screen_rects(), x, y if isinstance(y, int) else None,
                self.window.width(), self.window.height(),
            )
            if rect is not None:
                x = round(x - (self.window.sprite_size[0] - self.window.normal_width) / 2)
                if isinstance(y, int):
                    self.window.move(x, y)
                    self.window.clamp_position(QRect(*rect))
                else:
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
        """窗口跑出所有屏幕就回默认位置，否则只夹边。拖动/下落中不动。"""
        if self.window.is_dragging or self.window.is_falling:
            return
        self.window.stop_motion()
        x, y, w, h = self.window.body_rect()
        cx, cy = x + w // 2, y + h // 2
        if any(rx <= cx < rx + rw and ry <= cy < ry + rh for rx, ry, rw, rh in self._screen_rects()):
            self.window.clamp_position()
        else:
            self.window.place_default()

    def set_size(self, height: int) -> None:
        self.window.set_height(height)
        self.window.clamp_position()
        self.state.save.window["height"] = height
        self.save_position()
        self.sync()
        self._try_time_speech()

    def set_language(self, code: str) -> None:
        """切换语言，立即生效并存档：之后的台词、菜单、状态文字都用新语言，旧气泡收起。"""
        self.lines.set_language(code)
        self.state.save.language = self.lines.lang
        self._speech.dismiss()
        if self.bubble is not None:
            self.bubble.set_font_fallback(self.lines.font_fallback)
            self.bubble.dismiss()
        if self._dialogue is not None and self._dialogue.isVisible():
            self._dialogue.refresh()
        self.scheduler.mark_dirty(self._now())
        self.sync()
        self._try_time_speech()

    def set_privacy(self, private: bool) -> None:
        self.state.save.privacy_mode = private
        self.activity.clear()  # 之前记下的文件名等不会在切换后冒出来
        self.scheduler.mark_dirty(self._now())
        self._try_time_speech()

    def set_muted(self, muted: bool) -> None:
        self.state.save.bubble_muted = muted
        if muted:
            self._speech.dismiss()
        if muted and self.bubble is not None:
            self.bubble.dismiss()
        self.scheduler.mark_dirty(self._now())
        self._try_time_speech()

    def select_expression(self, name: str) -> None:
        self.window.stop_motion()
        self.state.select_expression(name, self._now())
        self.sync()
        self._try_time_speech()

    def fix_expression(self, fixed: bool) -> None:
        self.window.stop_motion()
        self.state.fix_expression(fixed, self._now())
        self.sync()
        self._try_time_speech()

    def set_activity(self, level: str) -> None:
        if level not in ACTIVITY_LEVELS:
            return
        self.state.save.activity_level = level
        self._idle.next_at = None
        self.scheduler.mark_dirty(self._now())
        self.sync()
        self._try_time_speech()

    def do_action(self, name: str) -> None:
        self.window.stop_motion()
        self.react(self.state.interact(self._now()))
        self._idle.next_at = None
        if name == "jump":
            self.window.jump()
        elif name == "turn":
            self.window.turn()
        elif name == "face":
            self.window.face(1 if QCursor.pos().x() >= self.window.geometry().center().x() else -1)
        elif name == "bed":
            self.state.menu_talk(self._now(), sleep=True)
            self.say_key("bedtime", category="dialogue")
        elif name == "desk":
            self.state.rest_at_desk(self._now())
            self.say_key("desk_rest", category="dialogue")
        self.sync()
        self._try_time_speech()

    def set_release_to_taskbar(self, on: bool) -> None:
        self.state.save.release_to_taskbar = on
        self.window.release_to_taskbar = on
        self.scheduler.mark_dirty(self._now())
        self._try_time_speech()

    def _pet_windows(self):
        return (self.window, self.bubble, self.overlay, self._crumbs,
                self.window._pause_badge, self.window._fps_overlay, self.window._sleep_z)

    def _dialog_windows(self):
        return (self._dialogue, self._input_panel, self._perm_panel, self._about)

    def _apply_topmost(self) -> None:
        if self.state.save.always_on_top:
            self._foreground.stop()
        for window in self._pet_windows():
            if window is not None:
                set_topmost(window, self.state.save.always_on_top)
        # Qt 重建诗音窗口后，确保已经打开的置顶对话框仍排在她前面。
        for window in self._dialog_windows():
            if window is not None:
                raise_without_activation(window)
        self._foreground.set_enabled(not self.state.save.always_on_top)

    def set_always_on_top(self, on: bool) -> None:
        self.state.save.always_on_top = on
        self._apply_topmost()
        self.scheduler.mark_dirty(self._now())
        self._try_time_speech()

    def _bring_forward(self) -> None:
        for window in (*self._pet_windows(), *self._dialog_windows()):
            if window is not None:
                raise_without_activation(window)

    # ------------------------------------------------------------ 来自 Claude 的事件
    def handle_event(self, etype: str, detail: Optional[str] = None, meta: Optional[dict] = None) -> None:
        """处理本地 HTTP 服务转来的事件（必须在 GUI 线程调用，见 bridge.py）。

        meta：hook 附带的会话信息 {"session", "tool_id", "proc"}（server.parse_meta 已校验）。
        """
        if etype in ("stop", "plan_ready"):
            detail = None  # 兼容旧 hook：回复/计划内容不显示、不记录
        meta = meta or {}
        session, tool_id = meta.get("session"), meta.get("tool_id")
        private = self.state.save.privacy_mode
        log.info("收到事件：%s %r %s", etype, None if private else detail, session or "")
        now = self._now()
        if etype == "pause_timeout":
            self._mark_end_pending(session)
            self._remember_ended(session)
            self.state.end_session(session)  # 这个会话的这一轮已经被 hook 结束了
            self._forget_session(session)
            self._on_pause_timeout()
            self.sync()
            return
        if etype == "work_stopped":
            # hook 在检查点拿到了 stop（等满上限或立即中断）：这个会话的这一轮结束了，不算完成任务
            self._mark_end_pending(session)
            self._remember_ended(session)
            self.state.end_session(session)
            self._forget_session(session)
            self.sync()
            return
        if etype == "tool_error" and session in self._interrupted:
            etype, detail = "tool_done", None  # 被“立即中断”结束的工具：本来就会失败，不说“出错了”
        if etype == "stop" and session and session in self._end_pending:
            # 诗音结束的这一轮（CC 随后照常发 Stop）：和 work_stopped 一样，不加任务数、不 done、不说完成、不催
            self._end_pending.discard(session)
            self._interrupted.discard(session)
            self._remember_ended(session)
            self.state.end_session(session)
            self._forget_session(session)
            self._sync_pause()
            self.sync()
            return
        if etype == "prompt" and session:
            self._end_pending.discard(session)  # 用户开始新的一轮
        if etype in ("prompt", "working") and self._ended and self._ended[0] == session:
            self._ended = None  # 用户自己在 CC 里接着说了
        if etype in ("prompt", "stop", "plan_ready"):
            self._interrupted.discard(session)
        self._track_session(etype, session, tool_id, meta.get("proc"))
        if etype in ("prompt", "stop"):
            self._sync_pause()  # 服务线程可能已经在 hub 里解除了暂停
        if etype == "notification" and detail == "idle_prompt" and session:
            self._tool_wall.pop(session, None)  # CC 在等输入：没有工具在跑（state 里同时清掉工作中）
        if etype == "tool_done":
            self.state.claude_event(etype, detail, now, session, tool_id)
            self.sync()
            return
        ui = self.lines.ui
        entry = make_entry(etype, detail, now)
        self.activity.add(entry)
        reactions = self.state.claude_event(etype, detail, now, session, tool_id)
        greeted = any(r.key in ("wake", "neglect_return") for r in reactions)  # 这句别被盖掉
        if etype == "working" and parse_working(detail):
            # 用“在读 x.py……”代替随机的“Claude 在努力中”
            reactions = [r for r in reactions if r.key != "claude_working"]
            self.react(reactions)
            if not greeted:
                self._say_activity(describe(entry, ui, private), now)
        else:
            self.react(reactions)
        if etype == "plan_ready":
            self.window.jump()
        self.sync()
        if etype in ("stop", "plan_ready"):
            self._bring_forward()

    def _say_activity(self, text: str, now: datetime) -> None:
        last = self._last_activity_say
        if last and last[0] == text and now - last[1] < ACTIVITY_REPEAT:
            return
        if self.say_text(text):
            self._last_activity_say = (text, now)

    # ------------------------------------------------------------ 会话
    def _track_session(self, etype: str, session: Optional[str], tool_id: Optional[str], proc) -> None:
        """记下立即中断要用的东西：CC 进程、在执行的工具开始时间（Unix 秒，和进程创建时间比较）。"""
        if not session:
            return
        if isinstance(proc, dict):
            self._procs[session] = interrupt.CCProcess(
                proc["pid"], proc["created"], proc["name"], proc.get("entry", ""), list(proc.get("hooks", [])))
        tools = self._tool_wall.setdefault(session, {})
        if etype == "working" and tool_id:
            tools[tool_id] = self._now().timestamp()
        elif etype in ("tool_done", "tool_error"):
            tools.pop(tool_id, None) if tool_id else tools.clear()
        elif etype in ("prompt", "stop", "plan_ready"):
            tools.clear()
        if etype in ("stop", "plan_ready"):
            self._forget_session(session)

    def _forget_session(self, session: Optional[str]) -> None:
        if session:
            self._procs.pop(session, None)
            self._tool_wall.pop(session, None)

    # ------------------------------------------------------------ 遥控：停下
    def stop_work(self) -> None:
        """“停下”：下一个检查点（工具调用前或做完后）hook 原地等待，直到点“继续”或在 CC 里说话。"""
        if self.state.paused:
            return
        self.react(self.state.interact(self._now()))
        self._held_said = self._held_seen = False
        self.hub.pause()
        self.state.paused = True
        if not self.state.save.bubble_muted:
            self._speech.dismiss()
            self.say(self.lines.ui("stop_requested"), priority=Priority.MEDIUM, category="stop_requested")
        self.sync()

    def resume_work(self, *, quiet: bool = False) -> None:
        """菜单上的“继续”：放行等待的 hook，无缝接着干（还没到检查点就点 = 取消停下）。"""
        was_paused = self.state.paused
        self.hub.resume()
        self._leave_pause()
        if not quiet and was_paused:
            self._speech.dismiss()
            self.say_key("resumed")
        self.sync()

    def _leave_pause(self) -> None:
        self.state.paused = False
        self._held_said = False
        self._held_seen = False

    def _sync_pause(self) -> None:
        """hub 在服务线程里被解除停下（用户在 CC 里说话，或这一轮没碰到检查点就结束了）后，把界面状态同步过来；
        hook 第一次真的在检查点等着时说一次“已经停下啦～”。"""
        if self.state.paused and not self.hub.is_paused:
            self._leave_pause()
        first_hold = self.state.paused and not self._held_seen and self.hub.is_holding
        if first_hold:
            self._held_seen = True  # 暂停标签和静音无关；sync() 里显示
        if self.state.paused and not self._held_said and self.hub.is_holding:
            self._held_said = True
            if not self.state.save.bubble_muted:
                self._speech.dismiss()  # 换掉“好，马上停～”
                self.say(self.lines.ui("work_held"), priority=Priority.MEDIUM, category="stop_requested")
        if first_hold:
            self.sync()  # 先创建/显示暂停标签，再将整个提示前移一次
            self._bring_forward()

    def _on_pause_timeout(self) -> None:
        """hook 停满上限后已返回 continue: false：放掉其他并行等待的 hook，提醒一次。只在停下等待中有效。"""
        if not self.state.paused:
            return
        self.hub.end()
        self._leave_pause()
        if not self.state.save.bubble_muted:
            self._speech.dismiss()
            self.say(self.lines.ui("work_stopped_timeout"), priority=Priority.HIGH, category="stop_requested")
        self.sync()

    # ------------------------------------------------------------ 遥控：立即中断
    def can_interrupt(self) -> bool:
        return bool(self.state.working_sessions(self._now()))

    def interrupt_work(self) -> None:
        """“立即中断”：结束所有工作中会话正在跑的工具进程，并让它们下一个检查点结束这一轮。

        只对工作中的会话做；做完把会话标成空闲（下一次 prompt / PreToolUse 之前不会再发）。
        一个都找不到对应进程时说明原因，退回普通的“停下”。
        """
        now = self._now()
        sessions = self.state.working_sessions(now)
        ui = self.lines.ui
        if not sessions:
            self.say(ui("interrupt_idle"), priority=Priority.MEDIUM, category="stop_requested")
            return
        self.react(self.state.interact(now))
        done = []
        for session in sessions:
            proc = self._procs.get(session)
            if proc is None:
                continue
            starts = list(self._tool_wall.get(session, {}).values())
            try:
                killed = interrupt.interrupt(proc, starts, self.process_view, self.hook_images)
            except Exception:
                log.exception("立即中断出错")
                killed = None
            if killed is not None:
                done.append(session)
        if not done:
            log.info("立即中断：没有找到对应的进程（会话 %s）", sessions)
            self._speech.dismiss()
            self.say(ui("interrupt_no_process"), priority=Priority.MEDIUM, category="stop_requested")
            if not self.state.paused:
                self.hub.pause()
                self.state.paused = True
                self._held_said = self._held_seen = False
            self.sync()
            return
        self.hub.request_interrupt(done)
        self._interrupted.update(done)
        self._end_pending.update(done)
        for session in done:
            self.state.end_session(session)
            self._tool_wall.pop(session, None)
        if self.state.paused and not self.state.working_sessions(now):
            self.hub.resume()  # 在等的 hook 先看到中断标记，返回 stop
            self._leave_pause()
        if not self.state.save.bubble_muted:
            self._speech.dismiss()
            self.say(ui("interrupted"), priority=Priority.HIGH, category="stop_requested")
        self.sync()

    # ------------------------------------------------------------ 遥控：这一轮结束后的继续
    def _mark_end_pending(self, session: Optional[str]) -> None:
        if session:
            self._end_pending.add(session)

    def _remember_ended(self, session: Optional[str]) -> None:
        if session:
            self._ended = (session, self._procs.get(session))

    def ended_is_terminal(self) -> bool:
        return self._ended is not None and interrupt.is_terminal(self._ended[1])

    def continue_ended(self) -> None:
        """这一轮已经被结束后的“继续”：终端版替用户发一句“继续”，桌面端复制到剪贴板。"""
        ended = self._ended
        if ended is None:
            return
        ui = self.lines.ui
        text = ui("continue_text")
        if not interrupt.is_terminal(ended[1]):
            QGuiApplication.clipboard().setText(text)
            self._ended = None
            self._say_continue("continue_copied")
            return
        if self._continue_sending:
            return
        self._continue_sending = True
        self.continue_runner(ended[1], text, lambda result: self._on_continue_result(ended, result))

    def _on_continue_result(self, ended, result: dict) -> None:
        self._continue_sending = False
        reason = None if result.get("ok") is True else result.get("reason")
        log.info("发送“继续”：%s", reason or "ok")
        if reason in (None, "gone") and self._ended is ended:
            self._ended = None  # 发过了，或者那个终端已经没了
        key = {None: "continue_sent", "draft": "continue_draft", "dialog": "continue_dialog"}.get(
            reason, "continue_failed")
        self._say_continue(key)

    def _say_continue(self, key: str) -> None:
        if self.state.save.bubble_muted:
            return
        self._speech.dismiss()
        self.say(self.lines.ui(key), priority=Priority.HIGH, category="stop_requested")

    def _run_console_send(self, proc: interrupt.CCProcess, text: str, done: Callable[[dict], None]) -> None:
        """在单独的子进程里附着 CC 的控制台发送（见 shion/console_send.py），结果回到 GUI 线程。"""
        qp = QProcess(self)
        qp.setProgram(sys.executable)
        qp.setArguments(["-m", "shion.console_send", "--pid", str(proc.pid), "--created", str(proc.created),
                         "--text", text])
        qp.setWorkingDirectory(str(ROOT))
        timer = QTimer(qp)
        timer.setSingleShot(True)
        timer.timeout.connect(qp.kill)
        finished = []

        def finish(*_):
            if finished:
                return
            finished.append(True)
            timer.stop()
            out = bytes(qp.readAllStandardOutput().data()).decode("utf-8", "replace").strip()
            try:
                result = json.loads(out.splitlines()[-1])
                result = result if isinstance(result, dict) else {"ok": False, "reason": "error"}
            except (ValueError, IndexError):
                result = {"ok": False, "reason": "error"}
            qp.deleteLater()
            done(result)

        qp.finished.connect(finish)
        qp.errorOccurred.connect(lambda err: finish() if err == QProcess.FailedToStart else None)
        timer.start(CONTINUE_SEND_TIMEOUT_MS)
        qp.start()

    # ------------------------------------------------------------ 遥控：同意 / 否决
    def _permission_texts(self) -> dict[str, str]:
        ui = self.lines.ui
        return {
            "title": ui("permission_title"), "allow": ui("permission_allow"), "deny": ui("permission_deny"),
            "more": ui("permission_more"), "expand": ui("permission_expand"),
            "collapse": ui("permission_collapse"),
        }

    def _sync_permission(self) -> None:
        """把排队中的授权请求显示出来：一次一条，按到达顺序；没人轮询的过期请求清掉。"""
        queue = self.hub.permissions
        queue.expire()
        pending = queue.pending()
        panel = self._perm_panel
        if not pending:
            if panel is not None and panel.isVisible():
                panel.hide_request()
            return
        if self._dialogue is not None:
            self._dialogue.hide()
        if panel is None:
            family = self.bubble.font_family if self.bubble is not None else "Consolas"
            panel = self._perm_panel = PermissionPanel(family, clock=self.window.monotonic_time)
            panel.decided.connect(self._on_permission_decided)
        head = pending[0]
        if panel.request_id != head.id:
            first = not panel.isVisible()
            panel.show_request(
                head.id, head.tool, head.detail, len(pending) - 1,
                self._permission_texts(), self.window.body_rect(),
            )
            if first:
                self.say_key("permission_request")
            self._bring_forward()
        else:
            panel.set_more(len(pending) - 1)

    def _on_permission_decided(self, rid: str, allow: bool) -> None:
        """用户点了面板上的按钮——这是 allow/deny 唯一的来源。"""
        if self.hub.permissions.decide(rid, allow):
            log.info("授权决定：%s", "同意" if allow else "否决")
        self._sync_permission()
        self._try_time_speech()

    def feedback_good(self) -> None:
        self.react(self.state.feedback_good(self._now()))
        self.sync()
        self._try_time_speech()

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
        self._try_time_speech()

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

    def dispose(self) -> None:
        """立刻在当前（GUI）线程销毁面板。测试收尾用：避免面板被别的线程里的垃圾回收销毁而崩溃。"""
        self._foreground.stop()
        self.state.cancel_snack()
        for panel in (self._perm_panel, self._input_panel, self._dialogue, self._crumbs):
            if panel is not None:
                panel.hide()
                panel.setParent(None)
                panel.deleteLater()
        self._perm_panel = self._input_panel = None
        self._dialogue = self._crumbs = None
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def quit(self) -> None:
        self._foreground.stop()
        self.window.stop_motion()
        self.state.cancel_snack()
        for panel in (self._dialogue, self._crumbs):
            if panel is not None:
                panel.hide()
        if self._perm_panel is not None:
            self._perm_panel.hide_request()
        try:
            self.scheduler.flush()  # 内部不抛异常；这里再兜一层，保证一定能退出
        except Exception:
            log.exception("退出时写存档失败")
        finally:
            self.quit_requested.emit()

    # ------------------------------------------------------------ 双击状态
    def status_text(self, now: Optional[datetime] = None) -> str:
        now = now or self._now()
        self.state._roll_stats(now)
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
        level, rules = self.state.affection_level, self.state.affection
        if rules is not None:
            item = rules.levels[level - 1]
            progress = ui("affection_max") if level == len(rules.levels) else ui(
                "affection_progress", current=save.affection - item.threshold,
                target=rules.levels[level].threshold - item.threshold)
            remaining = self.state.affection_remaining(now, (i.id for i in self.menu_content.visible("talks", level)))
            text += "\n" + ui("affection_status", level=level, name=localized(item.name, self.lines.lang),
                               progress=progress, remaining=remaining)
        if save.fixed_expression:
            text += "\n" + ui("expression_fixed")
        return text

    def _show_status(self) -> None:
        text = self.status_text()
        recent = self.activity.recent_lines(self.lines.ui, self.state.save.privacy_mode)
        if recent:
            text += "\n" + self.lines.ui("recent_header") + "\n" + "\n".join(recent)
        self.say(text)
        self._try_time_speech()

    # ------------------------------------------------------------ 菜单
    def _mouth_anchor(self) -> QPoint:
        x, y, w, h = self.window.body_rect()
        return QPoint(x + w // 2, y + round(h * MOUTH_FRACTION))

    def open_dialogue(self) -> None:
        if self.hub.permissions.pending():
            return
        self.window.stop_motion()
        self._idle.next_at = None
        if self._dialogue is None:
            family = self.bubble.font_family if self.bubble is not None else "Consolas"
            self._dialogue = DialoguePanel(self.menu_content, self.lines, family)
            self._dialogue.chosen.connect(self.choose_dialogue)
        self._dialogue.level = self.state.affection_level
        self._dialogue.open(self.window.body_rect(), busy=self.state.eating)

    def choose_dialogue(self, kind: str, ident: str) -> None:
        if kind not in ("snacks", "talks"):
            return
        item = self.menu_content.find(kind, ident)
        if item is None or item not in self.menu_content.visible(kind, self.state.affection_level):
            return
        now = self._now()
        if kind == "snacks":
            if self.state.eating:
                return
            if not self.state.start_snack(now):
                self.state.menu_talk(now)
                self.say_text(localized(self.menu_content.full, self.lines.lang),
                              priority=Priority.MEDIUM, category="snack_full")
                self.sync()
                return
            self.window.stop_motion()
            if self._crumbs is None:
                self._crumbs = CrumbOverlay(clock=self.window.monotonic_time, autostart=self._autostart)
                set_topmost(self._crumbs, self.state.save.always_on_top)
            self._crumbs.start(self._mouth_anchor(), self.state.save.window["height"],
                               self.state.config.eating_for.total_seconds())
        response = item.responses[0]
        if not self.state.save.bubble_muted and self._speech.allows(
                self.window.monotonic_time(), Priority.MEDIUM, "dialogue"):
            response = self.menu_content.pick(kind, item, self.lines.lang)
            self.say_text(localized(response.text, self.lines.lang), priority=Priority.MEDIUM, category="dialogue")
        if kind == "talks":
            self.state.menu_talk(now, response.expression, sleep=item.action == "sleep")
            self.react(self.state.gain_affection("talk", now, item.id))
        self.sync()
        self._try_time_speech()

    def build_menu(self) -> QMenu:
        menu = QMenu()
        ui = self.lines.ui
        menu.addAction(ui("menu_talk")).triggered.connect(self.open_dialogue)
        remote_menu = menu.addMenu(ui("menu_remote"))
        if self.state.paused:
            remote_menu.addAction(ui("menu_resume")).triggered.connect(self.resume_work)
        else:
            if self._ended is not None:  # 这一轮已经结束：终端发送“继续”，桌面端复制
                label = ui("menu_continue_send") if self.ended_is_terminal() else ui("menu_resume")
                act = remote_menu.addAction(label)
                act.setEnabled(not self._continue_sending)
                act.triggered.connect(self.continue_ended)
            remote_menu.addAction(ui("menu_stop")).triggered.connect(self.stop_work)
        interrupt_action = remote_menu.addAction(ui("menu_interrupt"))
        interrupt_action.setEnabled(self.can_interrupt())
        interrupt_action.triggered.connect(self.interrupt_work)
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
        for name in ("jump", "turn", "face", "bed", "desk"):
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

        release = menu.addAction(ui("menu_release_to_taskbar"))
        release.setCheckable(True)
        release.setChecked(self.state.save.release_to_taskbar)
        release.triggered.connect(self.set_release_to_taskbar)

        topmost = menu.addAction(ui("menu_always_on_top"))
        topmost.setCheckable(True)
        topmost.setChecked(self.state.save.always_on_top)
        topmost.triggered.connect(self.set_always_on_top)

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
        self._idle.next_at = None
        # 浏览/取消菜单不算交互，只有选中具体操作才改变状态或动作。
        menu = self.build_menu()
        self._menu_open = True
        try:
            menu.exec(pos)
        finally:
            self._menu_open = False
            menu.deleteLater()

    def show_about(self) -> None:
        box = self._about = QMessageBox(self.window)
        box.setWindowTitle(self.lines.ui("about_title"))
        box.setText(self.lines.ui("about_body", version=__version__))
        box.setTextFormat(Qt.PlainText)
        box.setStandardButtons(QMessageBox.Ok)
        box.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        # exec 内布局完成后再按实际原生边框定位，避免系统默认居中盖住诗音。
        QTimer.singleShot(0, lambda: position_dialog(box, self.window.body_rect()))
        try:
            box.exec()
        finally:
            self._about = None
            box.deleteLater()
