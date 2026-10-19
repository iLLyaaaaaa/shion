"""带输入框/按钮的终端风格小面板（和气泡同样的配色和字体）。

用途：写“有问题”的反馈（一行输入框）。面板由用户主动打开，所以可以拿到键盘焦点。
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

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
