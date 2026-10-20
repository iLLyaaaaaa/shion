"""带输入框/按钮的终端风格小面板（和气泡同样的配色和字体）。

用途：InputPanel 写“有问题”的反馈（一行输入框，用户主动打开，所以可以拿键盘焦点）；
PermissionPanel 接管同意/否决、HoldPanel 在检查点选“继续/结束这一轮”（都自动弹出，不抢焦点）。
"""
from __future__ import annotations

import time
from typing import Callable, Optional

from PySide6.QtCore import QPoint, QTimer, Qt, Signal
from PySide6.QtGui import QGuiApplication, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from shion.bubble import BG, BORDER, FG, FONT_PX, place_bubble

PANEL_WIDTH = 300
STYLE = f"""
QWidget#panel {{ background: {BG.name()}; border: 1px solid {BORDER.name()}; border-radius: 4px; }}
QLabel {{ color: {FG.name()}; font-size: {FONT_PX}px; }}
QLineEdit {{ background: #1A1A1A; color: {FG.name()}; border: 1px solid #555; padding: 3px;
            font-size: {FONT_PX}px; selection-background-color: {BORDER.name()}; }}
QPushButton {{ background: #1A1A1A; color: {FG.name()}; border: 1px solid {BORDER.name()};
              border-radius: 3px; padding: 4px 14px; font-size: {FONT_PX}px; }}
QPushButton:hover {{ background: {BORDER.name()}; color: #0A0A0A; }}
"""


class InputPanel(QWidget):
    """一行输入框 + 发送/取消。Enter 发送，Esc 取消；内容可留空。"""

    submitted = Signal(str)
    cancelled = Signal()

    def __init__(self, font_family: str = "Consolas"):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setObjectName("panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(PANEL_WIDTH)
        self.setStyleSheet(STYLE + f"* {{ font-family: '{font_family}'; }}")

        self._title = QLabel()
        self._title.setWordWrap(True)
        self._edit = QLineEdit()
        self._edit.setMaxLength(200)
        self._ok = QPushButton()
        self._cancel = QPushButton()
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self._cancel)
        buttons.addWidget(self._ok)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.addWidget(self._title)
        layout.addWidget(self._edit)
        layout.addLayout(buttons)

        self._ok.clicked.connect(self._submit)
        self._cancel.clicked.connect(self._cancel_clicked)
        self._edit.returnPressed.connect(self._submit)

    def open(self, title: str, ok_text: str, cancel_text: str,
             body: tuple[int, int, int, int]) -> None:
        """显示在 body（精灵本体矩形）头顶；清空上次输入。"""
        self._title.setText(title)
        self._ok.setText(ok_text)
        self._cancel.setText(cancel_text)
        self._edit.clear()
        self.adjustSize()
        screen = QGuiApplication.screenAt(QPoint(body[0] + body[2] // 2, body[1] + body[3] // 2)) \
            or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        x, y = place_bubble(body, (self.width(), self.height()), (g.x(), g.y(), g.width(), g.height()))
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()
        self._edit.setFocus()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self._cancel_clicked()
        else:
            super().keyPressEvent(event)

    def _submit(self) -> None:
        text = self._edit.text()
        self.hide()
        self.submitted.emit(text)

    def _cancel_clicked(self) -> None:
        self.hide()
        self.cancelled.emit()


ARM_DELAY = 0.6  # 面板出现（或换成下一条）后，这么久之内按钮点了也不算，防误点
COLLAPSED_H = 112
EXPANDED_H = 300
LONG_CHARS = 240
LONG_LINES = 6
PERMISSION_WIDTH = 400


class MouseOnlyButton(QPushButton):
    """只响应鼠标点击：空格/回车等按键一律忽略，不可能被误按键“同意”。"""

    def keyPressEvent(self, event) -> None:
        event.ignore()

    def keyReleaseEvent(self, event) -> None:
        event.ignore()


class PermissionPanel(QWidget):
    """同意/否决面板：显示要执行的命令或要改的文件，两个大按钮，一次只显示一条。

    决定只会从这两个按钮的点击里产生（signal decided）。面板不抢键盘焦点，不响应任何键盘操作，
    所以你在 CC 里打字时不会被它打断，也不会被一次回车误确认。
    """

    decided = Signal(str, bool)  # 请求 id，True = 同意

    def __init__(self, font_family: str = "Consolas", clock: Callable[[], float] = time.monotonic):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("panel")
        self.setFixedWidth(PERMISSION_WIDTH)
        self.setStyleSheet(
            STYLE + f"""
            * {{ font-family: '{font_family}'; }}
            QPlainTextEdit {{ background: #141414; color: {FG.name()}; border: 1px solid #444;
                              font-size: {FONT_PX}px; }}
            QPushButton#allow {{ background: {BORDER.name()}; color: #0A0A0A; font-weight: bold; }}
            QPushButton#allow:disabled, QPushButton#deny:disabled {{ background: #333; color: #777;
                                                                    border-color: #444; }}
            QPushButton#toggle {{ padding: 1px 8px; }}
            """
        )
        self._clock = clock
        self._rid: Optional[str] = None
        self._armed_at = 0.0
        self._expanded = False
        self._texts: dict[str, str] = {}
        self._more = 0

        self._title = QLabel()
        self._title.setWordWrap(True)
        self._detail = QPlainTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setFocusPolicy(Qt.NoFocus)
        self._detail.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self._toggle = QPushButton()
        self._toggle.setObjectName("toggle")
        self._toggle.setFocusPolicy(Qt.NoFocus)
        self._more_label = QLabel()
        self._allow = MouseOnlyButton()
        self._allow.setObjectName("allow")
        self._deny = MouseOnlyButton()
        self._deny.setObjectName("deny")
        for b in (self._allow, self._deny):
            b.setFocusPolicy(Qt.NoFocus)
            b.setMinimumHeight(36)

        top = QHBoxLayout()
        top.addWidget(self._title, 1)
        top.addWidget(self._toggle)
        bottom = QHBoxLayout()
        bottom.addWidget(self._more_label, 1)
        bottom.addWidget(self._deny)
        bottom.addWidget(self._allow)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.addLayout(top)
        layout.addWidget(self._detail)
        layout.addLayout(bottom)

        self._allow.clicked.connect(lambda: self._click(True))
        self._deny.clicked.connect(lambda: self._click(False))
        self._toggle.clicked.connect(self._toggle_expanded)

        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self.refresh_enabled)

    # ---- 对外 ----
    @property
    def request_id(self) -> Optional[str]:
        return self._rid

    def armed(self) -> bool:
        return self._clock() >= self._armed_at

    def show_request(self, rid: str, tool: str, detail: str, more: int, texts: dict[str, str],
                     body: tuple[int, int, int, int]) -> None:
        """显示一条请求（出现或换成下一条都从这里进来）；按钮 ARM_DELAY 秒后才生效。"""
        self._rid = rid
        self._texts = texts
        self._armed_at = self._clock() + ARM_DELAY
        self._expanded = False
        self._detail.setPlainText(detail)
        self._detail.moveCursor(QTextCursor.Start)
        long_text = len(detail) > LONG_CHARS or detail.count("\n") >= LONG_LINES
        self._toggle.setVisible(long_text)
        self._allow.setText(texts["allow"])
        self._deny.setText(texts["deny"])
        self._title.setText(f"{texts['title']}  [{tool}]")
        self.set_more(more)
        self._apply_height()
        self.refresh_enabled()
        self.follow(body)
        if not self.isVisible():
            self.show()
        self.raise_()
        self._timer.start()

    def set_more(self, n: int) -> None:
        self._more = n
        self._more_label.setText(self._texts["more"].format(n=n) if n > 0 else "")

    def follow(self, body: tuple[int, int, int, int]) -> None:
        screen = QGuiApplication.screenAt(QPoint(body[0] + body[2] // 2, body[1] + body[3] // 2)) \
            or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        x, y = place_bubble(body, (self.width(), self.height()), (g.x(), g.y(), g.width(), g.height()))
        self.move(x, y)

    def hide_request(self) -> None:
        self._rid = None
        self._timer.stop()
        self.hide()

    def refresh_enabled(self) -> None:
        on = self._rid is not None and self.armed()
        self._allow.setEnabled(on)
        self._deny.setEnabled(on)

    # ---- 内部 ----
    def _apply_height(self) -> None:
        self._detail.setFixedHeight(EXPANDED_H if self._expanded else COLLAPSED_H)
        self._toggle.setText(self._texts["collapse" if self._expanded else "expand"])
        self.adjustSize()

    def _toggle_expanded(self) -> None:
        self._expanded = not self._expanded
        self._apply_height()

    def _click(self, allow: bool) -> None:
        # 防误点：刚出现/刚换成下一条的 ARM_DELAY 内，即使按钮事件进来了也不算
        if self._rid is None or not self.armed():
            return
        self.decided.emit(self._rid, allow)


HOLD_BUTTON_H = 44


class HoldPanel(QWidget):
    """检查点等待面板：工作停在检查点时弹出，两个大按钮“继续”/“结束这一轮”。

    规则同 PermissionPanel：不抢键盘焦点、只响应鼠标、出现后 ARM_DELAY 秒内点击无效。
    """

    chosen = Signal(str)  # "continue" | "end"

    def __init__(self, font_family: str = "Consolas", clock: Callable[[], float] = time.monotonic):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("panel")
        self.setFixedWidth(PANEL_WIDTH)
        self.setStyleSheet(
            STYLE + f"""
            * {{ font-family: '{font_family}'; }}
            QPushButton#continue {{ background: {BORDER.name()}; color: #0A0A0A; font-weight: bold; }}
            QPushButton#continue:disabled, QPushButton#end:disabled {{ background: #333; color: #777;
                                                                      border-color: #444; }}
            """
        )
        self._clock = clock
        self._armed_at = 0.0
        self._open = False

        self._title = QLabel()
        self._title.setWordWrap(True)
        self._continue = MouseOnlyButton()
        self._continue.setObjectName("continue")
        self._end = MouseOnlyButton()
        self._end.setObjectName("end")
        for b in (self._continue, self._end):
            b.setFocusPolicy(Qt.NoFocus)
            b.setMinimumHeight(HOLD_BUTTON_H)
        buttons = QHBoxLayout()
        buttons.addWidget(self._end, 1)
        buttons.addWidget(self._continue, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.addWidget(self._title)
        layout.addLayout(buttons)

        self._continue.clicked.connect(lambda: self._click("continue"))
        self._end.clicked.connect(lambda: self._click("end"))

        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self.refresh_enabled)

    @property
    def is_open(self) -> bool:
        return self._open

    def armed(self) -> bool:
        return self._clock() >= self._armed_at

    def show_hold(self, texts: dict[str, str], body: tuple[int, int, int, int]) -> None:
        """弹出面板；按钮 ARM_DELAY 秒后才生效。"""
        self._open = True
        self._armed_at = self._clock() + ARM_DELAY
        self._title.setText(texts["title"])
        self._continue.setText(texts["continue"])
        self._end.setText(texts["end"])
        self.adjustSize()
        self.refresh_enabled()
        self.follow(body)
        if not self.isVisible():
            self.show()
        self.raise_()
        self._timer.start()

    def follow(self, body: tuple[int, int, int, int]) -> None:
        screen = QGuiApplication.screenAt(QPoint(body[0] + body[2] // 2, body[1] + body[3] // 2)) \
            or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        x, y = place_bubble(body, (self.width(), self.height()), (g.x(), g.y(), g.width(), g.height()))
        self.move(x, y)

    def hide_hold(self) -> None:
        self._open = False
        self._timer.stop()
        self.hide()

    def refresh_enabled(self) -> None:
        on = self._open and self.armed()
        self._continue.setEnabled(on)
        self._end.setEnabled(on)

    def _click(self, choice: str) -> None:
        # 防误点：刚出现的 ARM_DELAY 内，即使按钮事件进来了也不算
        if not self._open or not self.armed():
            return
        self.chosen.emit(choice)
