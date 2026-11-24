"""检查点暂停标签：终端配色，只收左键，不抢焦点，出现后延迟解锁。

只有一个会话停住时是一个文字标签（PauseBadge）；多个会话同时停住时换成 CheckpointPanel，每个会话一行，
可以分别“继续 / 结束这一轮”。
"""
from __future__ import annotations

import math
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase, QFontMetricsF, QImage, QPainter, QPainterPath, QRegion
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QLayout, QVBoxLayout, QWidget

from shion.bubble import BG, BORDER, FG, FONT_PX, PAD_X, PAD_Y, pick_font_family
from shion.budget_policy import BUDGET_TIERS, budget_number
from shion.budget_ui import BudgetInput
from shion.panel import ARM_DELAY, STYLE, MouseOnlyButton
from shion.sessions import LABEL_W as SESSION_LABEL_W
from shion.windowing import set_topmost

BADGE_X = 0.76
BADGE_Y = 0.05
CORNER_RADIUS = 4


def label_font(fallback=()) -> QFont:
    have = QFontDatabase.families()
    family = pick_font_family(have, QFontDatabase.systemFont(QFontDatabase.FixedFont).family())
    font = QFont(family)
    font.setPixelSize(FONT_PX)
    font.setStyleHint(QFont.Monospace)
    font.setFamilies([family, *(f for f in fallback if f in have and f != family)])
    return font


def badge_size(text: str, font: QFont) -> tuple[int, int]:
    metrics = QFontMetricsF(font)
    return math.ceil(metrics.horizontalAdvance(text)) + PAD_X * 2, math.ceil(metrics.height()) + PAD_Y * 2


def badge_geometry(body, size, avail, jump_offset=0.0) -> tuple[int, int]:
    """头顶右侧，随跳跃移动，按标签实际宽高夹在可用屏内。"""
    bx, by, bw, bh = body
    ax, ay, aw, ah = avail
    w, h = size
    x = round(bx + bw * BADGE_X - w / 2)
    y = round(by + bh * BADGE_Y - h / 2 - jump_offset)
    return max(ax, min(x, ax + aw - w)), max(ay, min(y, ay + ah - h))


def paint_badge(p: QPainter, size, text: str, font: QFont) -> None:
    w, h = size
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(BORDER)
    p.setBrush(BG)
    p.drawRoundedRect(QRectF(.5, .5, w - 1, h - 1), CORNER_RADIUS, CORNER_RADIUS)
    p.setPen(FG)
    p.setFont(font)
    p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, text)


def render_badge(text: str, font: QFont) -> QImage:
    size = badge_size(text, font)
    img = QImage(*size, QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    paint_badge(p, size, text, font)
    p.end()
    return img


class PauseBadge(QWidget):
    activated = Signal()

    def __init__(self, pet):
        super().__init__(pet, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        set_topmost(self, bool(pet.windowFlags() & Qt.WindowStaysOnTopHint))
        self.setFocusPolicy(Qt.NoFocus)
        self.setContextMenuPolicy(Qt.PreventContextMenu)
        self.setCursor(Qt.PointingHandCursor)
        self.pet = pet
        self._clock = pet.monotonic_time
        self.wanted = False
        self._armed_at = math.inf
        self._pressed = False
        self._config = None
        self.text = ""
        self.set_texts("暂停中", "点一下继续")
        pet.moved.connect(self.follow)

    def set_texts(self, text: str, tooltip: str, fallback=()) -> None:
        config = (text, tooltip, tuple(fallback))
        if config == self._config:
            return
        self._config = config
        self.text = text
        self.setToolTip(tooltip)
        self.setFont(label_font(fallback))
        self.resize_to(self.pet.sprite_height)
        self.update()

    def resize_to(self, _sprite_height: int) -> None:
        # 字号/内边距与气泡一致；宽度按三语文字实际测量。
        self.setFixedSize(*badge_size(self.text, self.font()))
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), CORNER_RADIUS, CORNER_RADIUS)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))
        self.follow()

    def set_wanted(self, on: bool) -> None:
        self.wanted = on
        if not on:
            self._pressed = False
        self.refresh()

    def refresh(self) -> None:
        if self.wanted and self.pet.isVisible():
            self.follow()
            if not self.isVisible():
                self.show()
                self.raise_()
        elif self.isVisible():
            self.hide()

    def showEvent(self, event) -> None:
        self._armed_at = self._clock() + ARM_DELAY
        self._pressed = False
        super().showEvent(event)

    def follow(self) -> None:
        if not self.wanted:
            return
        avail = self.pet._screen_avail(self.pet.geometry().center())
        x, y = badge_geometry(self.pet.body_rect(), (self.width(), self.height()),
                             (avail.x(), avail.y(), avail.width(), avail.height()), self.pet._jump_offset)
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    def mousePressEvent(self, event) -> None:
        self._pressed = (event.button() == Qt.LeftButton and self._clock() >= self._armed_at
                         and self.rect().contains(event.position().toPoint()))
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            event.ignore()
            return
        accepted = (self._pressed and self.wanted and self.isVisible()
                    and self._clock() >= self._armed_at and self.rect().contains(event.position().toPoint()))
        self._pressed = False
        if accepted:
            self.activated.emit()
        event.accept()

    def keyPressEvent(self, event) -> None:
        event.ignore()

    def keyReleaseEvent(self, event) -> None:
        event.ignore()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        paint_badge(p, (self.width(), self.height()), self.text, self.font())
        p.end()


LABEL_W = SESSION_LABEL_W  # 面板里会话名最多多宽（逻辑像素），超出加省略号（全文在 tooltip），同工作遥控菜单
LINE_H = round(FONT_PX * 1.6)  # 文字行高下限：备选字体（中日文）的字形比等宽首选字体高，留够不被裁


def checkpoint_geometry(body, size, avail, jump_offset=0.0) -> tuple[int, int]:
    """面板中心对准暂停标签的位置（头顶右侧），底边落在标签中线，向上展开；夹进可用屏。"""
    bx, by, bw, bh = body
    ax, ay, aw, ah = avail
    w, h = size
    x = round(bx + bw * BADGE_X - w / 2)
    y = round(by + bh * BADGE_Y - h - jump_offset)
    return max(ax, min(x, ax + aw - w)), max(ay, min(y, ay + ah - h))


class CheckpointPanel(QWidget):
    """多个会话同时停在检查点：标题“暂停中”，每个会话一行“名称  [继续] [结束这一轮]”。

    和授权面板同样的规矩：不抢焦点、按钮只响应鼠标，出现后（或停住的会话变了）ARM_DELAY 秒内点击无效。
    """

    resume_clicked = Signal(str)
    end_clicked = Signal(str)
    budget_selected = Signal(str, object, object)

    def __init__(self, pet, fallback=()):
        super().__init__(pet, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_StyledBackground, True)
        set_topmost(self, bool(pet.windowFlags() & Qt.WindowStaysOnTopHint))
        self.setFocusPolicy(Qt.NoFocus)
        self.setContextMenuPolicy(Qt.PreventContextMenu)
        self.setObjectName("panel")
        self.setStyleSheet(STYLE + "QPushButton { padding: 2px 10px; }")
        self.setFont(label_font(fallback))  # 与暂停标签同一套字体：等宽首选 + 中日文备选
        self.pet = pet
        self._clock = pet.monotonic_time
        self._armed_at = math.inf
        self._rows: list[tuple[str, str]] = []
        self._texts: dict[str, str] = {}
        self._budgets = {}
        self._budget_input = None
        self.wanted = False
        self._title = QLabel()
        self._title.setTextFormat(Qt.PlainText)
        self._title.setMinimumHeight(LINE_H)
        self._grid = QGridLayout()
        self._grid.setHorizontalSpacing(6)
        self._grid.setVerticalSpacing(4)
        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QLayout.SetFixedSize)  # 窗口大小始终跟内容走（样式表生效后也对）
        layout.setContentsMargins(10, 6, 10, 8)
        layout.setSpacing(6)
        layout.addWidget(self._title)
        layout.addLayout(self._grid)
        self.buttons: dict[str, tuple[MouseOnlyButton, MouseOnlyButton]] = {}
        pet.moved.connect(self.follow)

    # ---- 对外 ----
    @property
    def rows(self) -> list[tuple[str, str]]:
        return list(self._rows)

    def armed(self) -> bool:
        return self._clock() >= self._armed_at

    def present(self, rows: list[tuple[str, str]], texts: dict[str, str], *, budgets=None) -> None:
        """rows：[(会话, 显示名)]，按开始停住的先后。会话集合或文字变了就重建并重新计时防误点。"""
        rows = list(rows)
        budgets = dict(budgets or {})
        if rows != self._rows or texts != self._texts or budgets != self._budgets:
            if self._budget_input is not None:
                session, hold, dialog = self._budget_input
                if budgets.get(session, (None,))[0] is not hold:
                    dialog.reject()
            if budgets != self._budgets or [r[0] for r in rows] != [r[0] for r in self._rows]:
                self._armed_at = self._clock() + ARM_DELAY
            self._rows, self._texts = rows, dict(texts)
            self._budgets = budgets
            self._rebuild()
        self.wanted = True
        self.refresh()

    def withdraw(self) -> None:
        if self._budget_input is not None:
            self._budget_input[2].reject()
        self.wanted = False
        self._rows = []
        self._budgets = {}
        self.refresh()

    def refresh(self) -> None:
        if self.wanted and self.pet.isVisible():
            self.follow()
            if not self.isVisible():
                self.show()
                self.layout().activate()
                self.follow()  # 显示后尺寸才最终确定，按最终尺寸再摆一次
                self.raise_()
        elif self.isVisible():
            self.hide()

    def follow(self) -> None:
        if not self.wanted:
            return
        avail = self.pet._screen_avail(self.pet.geometry().center())
        x, y = checkpoint_geometry(self.pet.body_rect(), (self.width(), self.height()),
                                   (avail.x(), avail.y(), avail.width(), avail.height()), self.pet._jump_offset)
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    # ---- 内部 ----
    def _rebuild(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        self.buttons = {}
        single_budget = len(self._rows) == 1 and bool(self._budgets)
        title = self._texts.get("title", "")
        if single_budget:
            name = self.fontMetrics().elidedText(self._rows[0][1], Qt.ElideRight, SESSION_LABEL_W)
            title = self._texts["named_title"].format(name=name)
        self._title.setText(title)
        for row, (session, name) in enumerate(self._rows):
            if session in self._budgets:
                self._grid.addWidget(self._budget_row(session, name), row, 0, 1, 3)
                continue
            if self._budgets:
                name = f"{name} · {self._texts['manual']}"
            label = QLabel(self.fontMetrics().elidedText(name, Qt.ElideRight, LABEL_W))
            label.setTextFormat(Qt.PlainText)  # 文件夹名是外部文字，不能按富文本解析
            label.setToolTip(name)
            label.setMinimumHeight(LINE_H)
            resume, end = MouseOnlyButton(self._texts.get("resume", "")), MouseOnlyButton(self._texts.get("end", ""))
            for b in (resume, end):
                b.setFocusPolicy(Qt.NoFocus)
            resume.clicked.connect(lambda _=False, s=session: self._click(self.resume_clicked, s))
            end.clicked.connect(lambda _=False, s=session: self._click(self.end_clicked, s))
            self._grid.addWidget(label, row, 0)
            self._grid.addWidget(resume, row, 1)
            self._grid.addWidget(end, row, 2)
            self.buttons[session] = (resume, end)
        self.ensurePolished()
        self.layout().activate()
        self.follow()

    def _budget_row(self, session, name):
        hold, manual = self._budgets[session]
        texts = self._texts
        lang = texts["lang"]
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        if len(self._rows) > 1:
            name = self.fontMetrics().elidedText(name, Qt.ElideRight, LABEL_W)
            layout.addWidget(QLabel(texts["named_title"].format(name=name),
                                    textFormat=Qt.PlainText))
        body = texts["used"].format(used=budget_number(hold.total, lang), budget=budget_number(hold.budget, lang))
        layout.addWidget(QLabel(body, textFormat=Qt.PlainText))
        if manual:
            note = QLabel(texts["also_manual"], textFormat=Qt.PlainText)
            note.setWordWrap(True)
            layout.addWidget(note)

        layout.addWidget(QLabel(texts["choose"], textFormat=Qt.PlainText))
        choices = QHBoxLayout()
        choices.setSpacing(6)
        for value, label in zip(BUDGET_TIERS, texts["tiers"]):
            if value > hold.total:
                button = MouseOnlyButton(label)
                button.clicked.connect(lambda _=False, v=value: self._select_budget(session, hold, v))
                choices.addWidget(button)
        custom = MouseOnlyButton(texts["custom"])
        custom.clicked.connect(lambda: self._custom_budget(session, hold))
        unlimited = MouseOnlyButton(texts["unlimited"])
        unlimited.clicked.connect(lambda: self._select_budget(session, hold, None))
        for button in (custom, unlimited):
            choices.addWidget(button)
        choices.addStretch()
        layout.addLayout(choices)
        end = MouseOnlyButton(texts["end"])
        end.clicked.connect(lambda: self._click(self.end_clicked, session))
        layout.addWidget(end, alignment=Qt.AlignRight)
        return widget

    def _select_budget(self, session, hold, value):
        if self._budgets.get(session, (None,))[0] is hold:
            self._click(self.budget_selected, session, hold, value)

    def _custom_budget(self, session, hold):
        if not self.armed() or not self.isVisible() or self._budget_input is not None:
            return
        if self._budgets.get(session, (None,))[0] is not hold:
            return
        texts = self._texts
        # Parent to the pet so the input can take focus while the checkpoint panel cannot.
        dialog = BudgetInput(self.pet, texts, None,
                             lambda value: self._select_budget(session, hold, value),
                             check=lambda value: texts["too_low"] if value <= hold.total else None)
        self._budget_input = session, hold, dialog

        def close():
            self._budget_input = None
            dialog.deleteLater()

        dialog.finished.connect(close)
        dialog.show()

    def _click(self, signal, session: str, *args) -> None:
        # 防误点：刚出现 / 停住的会话刚变过的 ARM_DELAY 内，即使按钮事件进来了也不算
        if self.wanted and self.isVisible() and self.armed() and any(s == session for s, _ in self._rows):
            signal.emit(session, *args)

    def keyPressEvent(self, event) -> None:
        event.ignore()

    def keyReleaseEvent(self, event) -> None:
        event.ignore()


def checkpoint_budget_texts(lines) -> dict:
    ui = lines.ui
    return {
        "title": ui("budget_title"), "named_title": ui("budget_named_title"), "lang": lines.lang,
        "choose": ui("budget_choose"),
        "used": ui("budget_used"), "manual": ui("budget_manual"),
        "also_manual": ui("budget_also_manual"),
        "tiers": tuple(ui(f"budget_tier_{size}") for size in (10, 50, 100)),
        "custom": ui("budget_custom"), "unlimited": ui("budget_unlimited"),
        "input": ui("budget_input"), "invalid": ui("budget_invalid"),
        "too_low": ui("budget_too_low"), "apply": ui("budget_apply"), "cancel": ui("panel_cancel"),
    }
