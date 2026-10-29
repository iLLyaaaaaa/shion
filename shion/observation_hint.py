"""Persistent, read-only permission reminder. No buttons or control signals."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from .panel import STYLE
from .windowing import position_dialog


class ObservationHint(QWidget):
    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_StyledBackground)
        self.setObjectName("panel")
        self.setStyleSheet(STYLE)
        self.setFixedWidth(300)
        self.label = QLabel()
        self.label.setTextFormat(Qt.PlainText)
        self.label.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.label)

    def present(self, text, body):
        if self.label.text() != text:
            self.label.setText(text)
            self.adjustSize()
        position_dialog(self, body)
        if not self.isVisible():
            self.show()
