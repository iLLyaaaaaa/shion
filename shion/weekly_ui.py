"""QPainter report card and non-activating weekly report window."""
from pathlib import Path
import os
from datetime import date, timedelta

from PySide6.QtCore import QPointF, QRectF, QSize, QStandardPaths, Qt
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QFontMetrics, QImage, QPainter, QPainterPath, QPen,
                           QRadialGradient, QTextLayout, QTextOption)
from PySide6.QtWidgets import (QApplication, QButtonGroup, QDialog, QFileDialog, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from shion.lines import Lines

ROOT = Path(__file__).resolve().parents[1]
FONTS = ['Microsoft YaHei', 'Yu Gothic', 'Consolas']
CARD_W, CARD_H = 1200, 1500
MIN_FONT = 28  # Smallest card text, measured on the 1200-wide card.
SCREEN_SHARE = 0.85
ACCENT, BACKGROUND = '#F4772E', '#1A1212'
STYLE = f"""
QDialog {{ background: {BACKGROUND}; }}
QLabel {{ color: #9C8A84; }}
QPushButton {{ background: #2A1E1B; color: {ACCENT}; border: 1px solid {ACCENT};
              border-radius: 6px; padding: 6px 16px; }}
QPushButton:hover {{ background: #3A2820; }}
QPushButton:checked, QPushButton:pressed {{ background: {ACCENT}; color: {BACKGROUND}; }}
"""


def card_font(lang, size, bold=False):
    font = QFont()
    font.setFamilies(['Yu Gothic UI', 'Yu Gothic', 'Microsoft YaHei', 'Consolas'] if lang == 'ja' else FONTS)
    font.setPixelSize(size)
    font.setBold(bold)
    font.setLetterSpacing(QFont.AbsoluteSpacing, 0)
    font.setWordSpacing(0)
    if lang == 'ja':
        font.setWeight(QFont.Bold if bold else QFont.Medium)
        # Proportional alternates avoid full-cell kana spacing in Japanese.
        font.setFeature(QFont.Tag.fromString('palt'), 1)
    return font


def number(value, lang):
    if lang in ('zh', 'ja'):
        big, small = ('億' if lang == 'ja' else '亿'), '万'
        if value >= 1e8 or round(value / 1e4) >= 10000:
            return f'{value / 1e8:.2f}{big}'
        if value >= 1e7:
            return f'{round(value / 1e4)}{small}'
        if value >= 1e4:
            return f'{value / 1e4:.1f}'.rstrip('0').rstrip('.') + small
        return str(int(value))
    if value >= 1e9 or round(value / 1e6) >= 1000:
        return f'{value / 1e9:.2f}B'
    if value >= 1e7:
        return f'{round(value / 1e6)}M'
    for scale, unit in ((1e6, 'M'), (1e3, 'K')):
        if value >= scale:
            return f'{value / scale:.1f}'.rstrip('0').rstrip('.') + unit
    return str(int(value))


def ensure_fonts():
    # Qt's Windows offscreen plugin may expose no system fonts. Read installed
    # fonts for snapshot QA; do not bundle or copy any font files.
    if not QFontDatabase.families():
        directory = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
        for filename in ('msyh.ttc', 'YuGothR.ttc', 'YuGothM.ttc', 'YuGothB.ttc', 'consola.ttf'):
            path = directory / filename
            if path.is_file():
                QFontDatabase.addApplicationFont(str(path))


LABEL, CARD_FILL, CARD_EDGE, PRIMARY = '#9C8A84', '#231917', '#33241F', '#F2EDEA'
SPRITE_RECT = QRectF(689, 225, 377, 430)  # Right of the total number, clear of the card grid.
SPRITE_CENTER = QPointF(SPRITE_RECT.center().x(), SPRITE_RECT.center().y())
GRID_TOP, GRID_GAP, CARD_W3 = 753, 20, 344
CHART_BASE, BAR_W, BAR_SLOT = 1372, 118, 1072 / 7
FOOTER_NAME = '诗音 · Shion'


def bar_center(day):
    return 64 + (day + 0.5) * BAR_SLOT


def bar_x(day):
    return 64 + day * BAR_SLOT + (BAR_SLOT - BAR_W) / 2


def range_label(start, end):
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    tail = f'{last:%Y.%m.%d}' if first.year != last.year else f'{last:%m.%d}'
    return f'{first:%Y.%m.%d} — {tail}'


def wrap_lines(font, value, width, max_lines):
    """Break text into at most max_lines lines (CJK-aware); the last one is elided."""
    layout = QTextLayout(value, font)
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(option)
    spans = []
    layout.beginLayout()
    while True:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(width)
        spans.append((line.textStart(), line.textLength()))
    layout.endLayout()
    lines = [value[a:a + n].strip() for a, n in spans]
    if len(lines) > max_lines:
        rest = value[spans[max_lines - 1][0]:].strip()
        lines = lines[:max_lines - 1] + [QFontMetrics(font).elidedText(rest, Qt.ElideRight, int(width))]
    return lines


def paint_card(painter, data, branding=True):
    """Draw the card in 1200x1500 card units; the caller sets any scale."""
    ensure_fonts()
    lang = data['lang']
    ui = Lines(lang).ui
    painter.fillRect(QRectF(0, 0, CARD_W, CARD_H), QColor(BACKGROUND))
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)

    def text(x, y, width, height, value, size=MIN_FONT, color=PRIMARY, bold=False,
             align=Qt.AlignLeft, baseline=None):
        font = card_font(lang, size, bold)
        painter.setFont(font)
        painter.setPen(QColor(color))
        # Fit localizations and large counts without clipping or overlap.
        while painter.fontMetrics().horizontalAdvance(value) > width and font.pixelSize() > MIN_FONT:
            font.setPixelSize(font.pixelSize() - 1)
            painter.setFont(font)
        value = painter.fontMetrics().elidedText(value, Qt.ElideRight, int(width))
        if baseline is not None:
            painter.drawText(QPointF(x, baseline), value)
        else:
            painter.drawText(QRectF(x, y, width, height), align | Qt.AlignVCenter, value)

    def wrapped(x, y, width, value, size, color, max_lines, step, bold=False):
        font = card_font(lang, size, bold)
        painter.setFont(font)
        painter.setPen(QColor(color))
        for i, part in enumerate(wrap_lines(font, value, width, max_lines)):
            painter.drawText(QRectF(x, y + i * step, width, step), Qt.AlignLeft | Qt.AlignVCenter, part)

    def box(x, y, width, height, accent=False):
        path = QPainterPath()
        path.addRoundedRect(QRectF(x + 1, y + 1, width - 2, height - 2), 20, 20)
        painter.setPen(QPen(QColor(ACCENT if accent else CARD_EDGE), 2))
        painter.setBrush(QColor(CARD_FILL))
        painter.drawPath(path)
        painter.setBrush(Qt.NoBrush)

    def stat_card(x, y, width, height, label, value, accent=False, note=None):
        box(x, y, width, height, accent)
        text(x + 22, y + 14, width - 44, 36, label, 28, LABEL)
        text(x + 22, y + 50, width - 44, 56, value, 44, ACCENT if accent else PRIMARY, accent)
        if note:
            wrapped(x + 22, y + 108, width - 44, note, 28, LABEL, 2, 36)

    # Top bar: title on the left, date centered under the sprite's axis.
    text(64, 64, 560, 46, '> SHION / WEEKLY' if lang == 'en' else '> SHION / ' + ui('weekly_report'), 28, ACCENT)
    text(SPRITE_CENTER.x() - 215, 64, 430, 46, range_label(data['start'], data['end']), 30, LABEL,
         align=Qt.AlignHCenter)

    # Soft glow centered on the sprite.
    glow = QRadialGradient(SPRITE_CENTER, 300)
    glow.setColorAt(0, QColor(244, 119, 46, 70))
    glow.setColorAt(1, QColor(244, 119, 46, 0))
    painter.setPen(Qt.NoPen)
    painter.setBrush(glow)
    painter.drawEllipse(SPRITE_CENTER, 300, 300)
    painter.setBrush(Qt.NoBrush)

    if data.get('ongoing'):
        text(64, 178, 620, 40, ui('weekly_title_label'), 28, LABEL)
        text(64, 222, 620, 140, ui('weekly_ongoing', n=data['day_n']), 128, ACCENT, True)
        sprite_name = 'idle'
    else:
        text(64, 178, 620, 40, ui('weekly_title_label'), 28, LABEL)
        text(64, 222, 620, 140, data['title']['name'], 128, ACCENT, True)
        wrapped(64, 372, 620, data['title']['comment'], 34, PRIMARY, 2, 46)
        sprite_name = data['title']['sprite']
    sprite = QImage(str(ROOT / 'assets/sprites' / (sprite_name + '.png')))
    if sprite.isNull():
        sprite = QImage(str(ROOT / 'assets/sprites/idle.png'))
    if not sprite.isNull():
        size = sprite.size().scaled(QSize(int(SPRITE_RECT.width()), int(SPRITE_RECT.height())), Qt.KeepAspectRatio)
        painter.drawImage(QRectF(SPRITE_RECT.x() + (SPRITE_RECT.width() - size.width()) / 2, SPRITE_RECT.y(),
                                 size.width(), size.height()), sprite)

    totals = data['totals']
    if data['enabled']:
        text(64, 484, 620, 40, ui('weekly_total'), 28, LABEL)
        text(64, 520, 620, 150, number(totals['total_tokens'], lang), 136, ACCENT, True, baseline=650)
    else:
        text(64, 560, 620, 80, ui('weekly_disabled'), 36, LABEL)
    if 'seven_day_peak' in totals:
        text(64, 676, 1072, 44, ui('weekly_quota', value=f"{totals['seven_day_peak']:g}"), 28, LABEL)

    # 3x2 card grid; the price card carries its own estimate note.
    peak = data.get('peak_day')
    peak_value = (date.fromisoformat(data['start']) + timedelta(days=peak)).strftime('%m-%d') if peak is not None else '—'
    cards = []
    if data['enabled']:
        note = ui('weekly_partial' if data['partial'] else 'weekly_estimate')
        note_lines = len(wrap_lines(card_font(lang, 28), note, CARD_W3 - 44, 2))
        cards += [dict(label=ui('weekly_output'), value=number(totals['output_tokens'], lang)),
                  dict(label=ui('weekly_price_label'), value=f"${data['price']:.2f}", note=note,
                       height=108 + 36 * note_lines + 16),
                  dict(label=ui('weekly_daily_avg'), value=number(data['daily_avg'], lang)),
                  dict(label=ui('weekly_active_days'), value=f"{data['active_days']}/{data['days_elapsed']}")]
    cards += [dict(label=ui('weekly_latest_label'), value=data['latest'] or '—'),
              dict(label=ui('weekly_peak'), value=peak_value, accent=True)]
    y = GRID_TOP
    for first in range(0, len(cards), 3):
        row = cards[first:first + 3]
        height = max([c.get('height', 124) for c in row])
        for i, c in enumerate(row):
            stat_card(64 + i * (CARD_W3 + GRID_GAP), y, CARD_W3, height, c['label'], c['value'],
                      c.get('accent', False), c.get('note'))
        y += height + GRID_GAP

    # Shion's own counters, only when something was recorded.
    if data.get('has_stats', True):
        chips = [('weekly_chip_tasks', str(totals['tasks'])), ('weekly_chip_hours', f"{totals['seconds'] / 3600:.1f} h"),
                 ('weekly_chip_approvals', str(totals['approvals'])), ('weekly_chip_denials', str(totals['denials'])),
                 ('weekly_chip_pats', str(totals['pats'])), ('weekly_chip_snacks', str(totals['snacks']))]
        gap = 14
        chip_w = (1072 - 5 * gap) / 6
        for i, (key, value) in enumerate(chips):
            x = 64 + i * (chip_w + gap)
            box(x, y, chip_w, 104)
            text(x + 12, y + 8, chip_w - 24, 36, ui(key), 28, LABEL)
            text(x + 12, y + 46, chip_w - 24, 50, value, 40)
        y += 104 + GRID_GAP

    # Bar chart fills the remaining height.
    text(64, y + 4, 1072, 40, ui('weekly_chart' if data['enabled'] else 'weekly_tasks'), 28, LABEL)
    max_height = max(40, min(320, CHART_BASE - (y + 4 + 40) - 48))
    future = data.get('future') or [False] * 7
    done = [v for v, f in zip(data['daily'], future) if not f]
    top = max(max(done, default=0), 1)
    for i, value in enumerate(data['daily']):
        x, center = bar_x(i), bar_center(i)
        label = (date.fromisoformat(data['start']) + timedelta(days=i)).strftime('%m-%d')
        if future[i]:
            painter.setPen(QPen(QColor('#4A3630'), 2, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRectF(x + 1, CHART_BASE - max_height + 1, BAR_W - 2, max_height - 2))
            text(center - 70, CHART_BASE + 6, 140, 36, label, 28, '#5A4A44', align=Qt.AlignHCenter)
            continue
        height = max(4, int(max_height * value / top))
        is_peak = i == peak
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, CHART_BASE - height, BAR_W, height + 12), 12, 12)
        painter.save()
        painter.setClipRect(QRectF(x, CHART_BASE - height, BAR_W, height))
        painter.fillPath(path, QColor(ACCENT if is_peak else '#5A3A2C'))
        painter.restore()
        text(center - 75, CHART_BASE - height - 42, 150, 38, number(value, lang), 28,
             ACCENT if is_peak else PRIMARY, is_peak, align=Qt.AlignHCenter)
        text(center - 70, CHART_BASE + 6, 140, 36, label, 28, LABEL, align=Qt.AlignHCenter)

    # Footer.
    if branding:
        text(64, 1432, 700, 40, 'github.com/iLLyaaaaaa/shion', 28, LABEL)
    text(836, 1432, 300, 40, FOOTER_NAME, 28, LABEL, align=Qt.AlignRight)


def render_card(data, branding=True):
    image = QImage(CARD_W, CARD_H, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor(BACKGROUND))
    painter = QPainter(image)
    try:
        paint_card(painter, data, branding)
    finally:
        painter.end()
    return image


class CardView(QWidget):
    """Repaints the card at the widget's real size instead of scaling a bitmap."""

    def __init__(self, data, branding):
        super().__init__()
        self.data, self.branding = data, branding
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def set_card_height(self, height):
        height = max(240, int(height))
        self.setFixedSize(round(height * CARD_W / CARD_H), height)

    def paintEvent(self, _event):
        painter = QPainter(self)
        try:
            painter.scale(self.width() / CARD_W, self.height() / CARD_H)
            paint_card(painter, self.data, self.branding)
        finally:
            painter.end()


class WeeklyWindow(QDialog):
    def __init__(self, data, branding=True, switch=None):
        # Showing never activates the window; an explicit user click can focus
        # it so the standard QDialog Escape action remains available.
        super().__init__(None, Qt.Tool)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setStyleSheet(STYLE)
        self.data, self.branding, self.switch = data, branding, switch
        self.image = render_card(data, branding)
        layout = QVBoxLayout(self)
        self.view = CardView(data, branding)
        layout.addWidget(self.view, 0, Qt.AlignHCenter)
        buttons = QHBoxLayout()
        self.prev_button, self.this_button = QPushButton(), QPushButton()
        group = QButtonGroup(self)
        for button, previous in ((self.prev_button, True), (self.this_button, False)):
            button.setCheckable(True)
            group.addButton(button)
            button.clicked.connect(lambda _=False, p=previous: self.switch and self.switch(p))
            buttons.addWidget(button)
        buttons.addStretch(1)
        self.save_button, self.copy_button = QPushButton(), QPushButton()
        self.save_button.clicked.connect(self.save_image)
        self.copy_button.clicked.connect(lambda: QApplication.clipboard().setImage(self.image))
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.copy_button)
        layout.addLayout(buttons)
        self.message = QLabel()
        layout.addWidget(self.message)
        self._texts()
        self._fit_screen()

    def _texts(self):
        ui = Lines(self.data['lang']).ui
        self.setWindowTitle(ui('weekly_report'))
        self.prev_button.setText(ui('weekly_switch_prev'))
        self.this_button.setText(ui('weekly_switch_this'))
        self.save_button.setText(ui('weekly_save'))
        self.copy_button.setText(ui('weekly_copy'))
        (self.this_button if self.data.get('ongoing') else self.prev_button).setChecked(True)

    def _fit_screen(self):
        # The whole window, controls included, takes 85% of the available height.
        screen = self.screen() or QApplication.primaryScreen()
        target = int(screen.availableGeometry().height() * SCREEN_SHARE) if screen else 800
        self.view.set_card_height(target / 2)
        extra = self.layout().sizeHint().height() - self.view.height()
        self.view.set_card_height(target - extra)
        self.setFixedSize(self.layout().sizeHint())
        self.target_height = target

    def update_report(self, data):
        self.data = data
        self.image = render_card(data, self.branding)
        self.view.data, self.view.branding = data, self.branding
        self._texts()
        self.view.update()

    def save_image(self):
        folder = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
        default = str(Path(folder) / ('Shion-weekly-' + self.data['start'] + '.png'))
        chosen, _ = QFileDialog.getSaveFileName(self, self.windowTitle(), default, 'PNG (*.png)')
        if chosen:
            ok = self.image.save(chosen, 'PNG')
            self.message.setText(Lines(self.data['lang']).ui('weekly_saved' if ok else 'weekly_failed'))
