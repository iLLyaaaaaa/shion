"""Task labels and screen placement shared by the live window and snapshots."""
from __future__ import annotations

from html import escape

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from shion.badge import CheckpointPanel, PauseBadge, badge_geometry, checkpoint_geometry, label_font
from shion.pet_window import LEGACY_JUMP_HEIGHT
from shion.bubble import BG, BORDER, FG
from shion.v3_display import desired_side
from shion.windowing import raise_without_activation, set_topmost

WIDTH, ROW, SPACING, GAP = 192, 26, 4, 10
BADGES = {"claude_code": "CC", "claude_chat": "Claude", "chatgpt": "GPT"}
DOTS = {"waiting": QColor("#855314"), "working": QColor("#75B9F8")}
DONE_MARK = QColor("#82CF9A")
GEOMETRY_EVENTS = (QEvent.Move, QEvent.Resize, QEvent.Show, QEvent.Hide)


def place_chips(body: QRect, pet_bounds: QRect, size: QSize, avail: QRect,
                obstacles: tuple[QRect, ...], side: str) -> QRect | None:
    """Find the closest free vertical slot on either side, preserving side priority."""
    if size.width() > avail.width() or size.height() > avail.height():
        return None
    height = size.height()
    min_y, max_y = avail.top(), avail.bottom() - height + 1
    preferred_y = body.center().y() + body.height() // 8 - height // 2
    clamp_y = lambda y: min(max_y, max(min_y, y))
    for candidate in (side, "left" if side == "right" else "right"):
        left = (pet_bounds.left() - GAP - size.width() if candidate == "left"
                else pet_bounds.right() + 1 + GAP)
        if left < avail.left() or left + size.width() - 1 > avail.right():
            continue
        strip = QRect(left, avail.top(), size.width(), avail.height())
        blocked = [rect.adjusted(-GAP, -GAP, GAP, GAP) for rect in obstacles]
        blocked = [rect for rect in blocked if strip.intersects(rect)]
        # A nearest free slot starts at the preferred position, a screen edge, or an obstacle edge.
        ys = {clamp_y(preferred_y), min_y, max_y}
        for rect in blocked:
            ys.update((clamp_y(rect.top() - height), clamp_y(rect.bottom() + 1)))
        for y in sorted(ys, key=lambda y: (abs(y - preferred_y), y)):
            rect = QRect(left, y, size.width(), height)
            if not any(rect.intersects(other) for other in blocked):
                return rect
    return None


class TaskChips(QWidget):
    def __init__(self, pet, *, available=None):
        super().__init__(pet, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.pet = pet
        self._available = available if available is not None else pet._screen_avail
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.NoFocus)
        self.setContextMenuPolicy(Qt.PreventContextMenu)
        set_topmost(self, bool(pet.windowFlags() & Qt.WindowStaysOnTopHint))
        self.view = None
        self.expanded = False
        self._offset = 0
        self._limit = 4
        self._side = "right"
        self._config = ()
        self._appearance = ()
        self._rows = ()
        self._shown_chips = ()
        self._obstacles = ()
        self._scene_overlay = None
        self._pressed = False
        self._relayout = QTimer(self, singleShot=True, interval=0)
        self._relayout.timeout.connect(self.follow)
        pet.installEventFilter(self)
        pet.visible_sprite_bounds_changed.connect(self.follow)

    def present(self, view, ui, fallback=(), obstacles=()):
        self.view = view
        config = (tuple(fallback), ui("task_board_clear"), ui("task_board_collapse"))
        appearance = tuple((chip.key, chip.name, chip.status, chip.wait_reason) for chip in view.all_chips)
        if config != self._config or appearance != self._appearance:
            QToolTip.hideText()
            self._pressed = False
            if config != self._config:
                self.setFont(label_font(fallback))
            self._config = config
            self._appearance = appearance
        if not view.overflow_count:
            self.expanded = False
            self._offset = 0
        if obstacles != self._obstacles:
            for widget in self._obstacles:
                if widget not in obstacles:
                    widget.removeEventFilter(self)
            self._obstacles = tuple(obstacles)
            for widget in self._obstacles:
                widget.installEventFilter(self)
        self.follow()

    def withdraw(self):
        if self.isVisible():
            QToolTip.hideText()
            self.hide()
        self._pressed = False
        self.expanded = False
        self._offset = 0

    def _layout(self, avail, body, pet_bounds, obstacles):
        view = self.view
        for limit in range(min(7, len(view.all_chips)), 0, -1) if self.expanded else (len(view.visible_chips),):
            if self.expanded:
                offset = min(self._offset, len(view.all_chips) - limit)
                chips = view.all_chips[offset:offset + limit]
            else:
                chips = view.visible_chips
            count = len(chips) + bool(view.overflow_count) + view.show_clear_done
            size = QSize(WIDTH, count * (ROW + SPACING) - SPACING)
            rect = place_chips(body, pet_bounds, size, avail, obstacles, self._side)
            if rect is not None:
                self._limit = limit
                if self.expanded:
                    self._offset = offset
                return rect, chips
        return None, ()

    def follow(self):
        pet = self.pet
        if (self.view is None or not self.view.all_chips or not pet.isVisible()
                or pet.is_dragging or pet.is_falling or pet.lifting):
            self.withdraw()
            return
        body = QRect(*pet.body_rect())
        avail = self._available(body.center())
        self._side = desired_side(body.center().x(), avail.x(), avail.width(), self._side)
        overlay = getattr(pet, "_v3_scene_overlay", None)
        if overlay is not self._scene_overlay:
            self._scene_overlay = overlay
            if overlay is not None:
                overlay.installEventFilter(self)
        bounds = pet.resting_sprite_bounds()
        obstacles = tuple(self._obstacle_bounds(widget, body, avail) for widget in self._obstacles
                          if widget.isVisible())
        rect, chips = self._layout(avail, body, bounds, obstacles)
        if rect is None or rect.intersects(pet.visible_sprite_bounds()):
            self.withdraw()
            return
        rows = [(chip.name, BADGES[chip.source], chip.status) for chip in chips]
        if self.view.overflow_count:
            rows.append((self._config[2] if self.expanded else f"+{self.view.overflow_count}", "", "toggle"))
        if self.view.show_clear_done:
            rows.append((self._config[1], "", "clear"))
        self._shown_chips = chips
        if self._rows != rows:
            self._rows = rows
            self.update()
        if self.geometry() != rect:
            self.setGeometry(rect)
        if not self.isVisible():
            self.show()
            raise_without_activation(self)

    @staticmethod
    def _obstacle_bounds(widget, body, avail):
        if isinstance(widget, (PauseBadge, CheckpointPanel)):
            layout = badge_geometry if isinstance(widget, PauseBadge) else checkpoint_geometry
            size = (widget.width(), widget.height())
            x, y = layout(body.getRect(), size, avail.getRect())
            top = layout(body.getRect(), size, avail.getRect(), LEGACY_JUMP_HEIGHT)[1]
            return QRect(x, top, size[0], y - top + size[1])
        return widget.geometry()

    def eventFilter(self, watched, event):
        if event.type() in GEOMETRY_EVENTS:
            if watched is self.pet and event.type() == QEvent.Hide:
                self.withdraw()
            elif event.type() != QEvent.Hide and self.isVisible():
                bounds = (self.pet.visible_sprite_bounds()
                          if watched is self.pet or watched is self._scene_overlay else watched.geometry())
                if self.geometry().intersects(bounds):
                    # A moved/resized surface can enter the old label rectangle before relayout.
                    self.hide()
            self._relayout.start()
        return False

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setFont(self.font())
        metrics = QFontMetrics(self.font())
        for i, (name, badge, status) in enumerate(self._rows):
            row = QRect(0, i * (ROW + SPACING), WIDTH, ROW)
            waiting = status == "waiting"
            painter.setPen(QColor("#D1A351") if waiting else BORDER)
            painter.setBrush(QColor("#FFE6A8") if waiting else BG)
            painter.drawRoundedRect(row.adjusted(1, 1, -1, -1), ROW / 2, ROW / 2)
            painter.setPen(QColor("#542F0E") if waiting else FG)
            if not badge:
                if status == "clear":
                    painter.setPen(QColor("#A59588"))
                painter.drawText(row, Qt.AlignCenter, name)
                continue
            painter.drawText(row.adjusted(10, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, badge)
            x = 10 + metrics.horizontalAdvance(badge) + 9
            text = row.adjusted(x, 0, -27, 0)
            painter.drawText(text, Qt.AlignVCenter | Qt.AlignLeft,
                             metrics.elidedText(name, Qt.ElideRight, text.width()))
            center = QPoint(WIDTH - 14, row.center().y())
            if status == "done":
                painter.setPen(QPen(DONE_MARK, 2.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                painter.drawPolyline([center + QPoint(-5, 0), center + QPoint(-2, 3), center + QPoint(5, -4)])
            else:
                painter.setPen(Qt.NoPen)
                painter.setBrush(DOTS[status])
                radius = 5 if status == "working" else 3
                painter.drawEllipse(center, radius, radius)

    def _row_at(self, pos):
        if self.rect().contains(pos) and pos.y() % (ROW + SPACING) < ROW:
            return pos.y() // (ROW + SPACING)
        return -1

    def event(self, event):
        if event.type() == QEvent.ToolTip:
            index = self._row_at(event.pos())
            if 0 <= index < len(self._shown_chips):
                text = "<qt>" + escape(self._shown_chips[index].tooltip).replace("\n", "<br>") + "</qt>"
                QToolTip.showText(event.globalPos(), text, self)
            else:
                QToolTip.hideText()
            return True
        return super().event(event)

    def mousePressEvent(self, event):
        self._pressed = (event.button() == Qt.LeftButton and self._toggle_at(event.position().toPoint()))
        event.setAccepted(self._pressed)

    def mouseReleaseEvent(self, event):
        toggle = self._pressed and event.button() == Qt.LeftButton and self._toggle_at(event.position().toPoint())
        self._pressed = False
        event.setAccepted(toggle)
        if toggle:
            self.expanded = not self.expanded
            self._offset = 0
            self.follow()

    def _toggle_at(self, pos):
        index = self._row_at(pos)
        return 0 <= index < len(self._rows) and self._rows[index][2] == "toggle"

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if not self.expanded or not delta:
            event.ignore()
            return
        offset = self._offset + (1 if delta < 0 else -1)
        self._offset = max(0, min(len(self.view.all_chips) - self._limit, offset))
        self.follow()
        event.accept()
