"""主动点击后才接收按键的终端对话窗口。"""
from PySide6.QtCore import QEvent, QTimer, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from shion.bubble import FONT_PX
from shion.windowing import position_dialog, raise_without_activation
from shion.menu_content import localized
from shion.panel import STYLE


class DialoguePanel(QWidget):
    chosen = Signal(str, str)

    def __init__(self, content, lines, font_family="Consolas"):
        super().__init__()
        self.content, self.lines = content, lines
        self._family = font_family
        self.page = "talks"
        self.keyboard_ready = False
        self.busy = False
        self.level = None
        self._body = (0, 0, 100, 100)
        self._choices = {}
        self._focus_check = QTimer(self)
        self._focus_check.setSingleShot(True)
        self._focus_check.timeout.connect(self._check_focus)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_StyledBackground)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setObjectName("panel")
        self.setFixedWidth(340)
        self.setStyleSheet(STYLE)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(10, 8, 10, 8)

    def open(self, body, busy=False):
        self.page, self.busy = "talks", busy
        self.keyboard_ready = False
        self._body = body
        self.refresh()
        self.show()  # WA_ShowWithoutActivating；禁止 activateWindow / setFocus
        raise_without_activation(self)

    def refresh(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.hide()
                widget.deleteLater()
        font = QFont()
        font.setFamilies([self._family, *self.lines.font_fallback])
        font.setPixelSize(FONT_PX)
        self.setFont(font)
        ui, lang = self.lines.ui, self.lines.lang
        self._choices = {}

        def label(text):
            w = QLabel(text)
            w.setTextFormat(Qt.PlainText)
            w.setWordWrap(True)
            w.installEventFilter(self)
            self._layout.addWidget(w)
            w.show()

        def button(number, text, kind, ident, enabled=True):
            w = QPushButton(f"{number}. {text}" if number is not None else text)
            w.setFocusPolicy(Qt.NoFocus)
            w.setEnabled(enabled)
            w.installEventFilter(self)
            w.clicked.connect(lambda _=False, k=kind, i=ident: self._choose(k, i))
            self._layout.addWidget(w)
            w.show()
            if number is not None and enabled:
                self._choices[number] = (kind, ident)

        label("> " + ui("dialogue_snacks" if self.page == "snacks" else "menu_talk"))
        if self.page == "talks":
            button(1, ui("dialogue_snacks"), "page", "snacks", bool(self.content.visible("snacks", self.level)) and not self.busy)
            entries, start = self.content.visible("talks", self.level), 2
        else:
            entries, start = self.content.visible("snacks", self.level), 1
        if not entries or self.page == "talks" and not self.content.visible("snacks", self.level):
            label(ui("dialogue_unavailable"))
        for number, entry in enumerate(entries, start):
            button(number, localized(entry.name, lang), self.page, entry.id,
                   not (self.page == "snacks" and self.busy))
        if self.busy:
            label(ui("dialogue_eating"))
        if self.page == "snacks":
            button(0, ui("dialogue_back"), "page", "talks")
        button(None, ui("dialogue_close"), "close", "")
        label(ui("dialogue_hint"))
        self._layout.activate()
        self.adjustSize()
        self.follow(self._body)

    def follow(self, body):
        self._body = body
        position_dialog(self, body)

    def _arm(self):
        self.keyboard_ready = True
        self.activateWindow()  # 仅在明确的鼠标按下之后
        self.setFocus(Qt.MouseFocusReason)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self._arm()
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._arm()
        super().mousePressEvent(event)

    def event(self, event):
        if event.type() == QEvent.WindowDeactivate:
            # Windows 首次显式激活会排入 deactivate→activate；按键仍须
            # isActiveWindow()，下一轮事件确认确实失焦才撤销点击授权。
            self._focus_check.start(0)
        elif event.type() == QEvent.Hide:
            self.keyboard_ready = False
        return super().event(event)

    def _check_focus(self):
        if not self.isActiveWindow():
            self.keyboard_ready = False

    def keyPressEvent(self, event):
        if not self.keyboard_ready or not self.isActiveWindow() or event.isAutoRepeat():
            event.ignore()
            return
        if event.modifiers() not in (Qt.NoModifier, Qt.KeypadModifier):
            event.ignore()
            return
        if event.key() == Qt.Key_Escape:
            self.hide()
        elif Qt.Key_0 <= event.key() <= Qt.Key_9:
            choice = self._choices.get(event.key() - Qt.Key_0)
            if choice:
                self._choose(*choice)
        else:
            event.ignore()

    def _choose(self, kind, ident):
        if kind == "page":
            self.page = ident
            self.refresh()
        elif kind == "close":
            self.hide()
        else:
            self.hide()
            self.chosen.emit(kind, ident)
