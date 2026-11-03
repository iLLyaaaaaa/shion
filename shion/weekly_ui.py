"""QPainter report card and non-activating weekly report window."""
from pathlib import Path
import os
from datetime import date, timedelta

from PySide6.QtCore import QPointF, QRectF, QSize, QStandardPaths, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPen
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


def bar_center(day):
    return 85 + day * 153 + 95 / 2


def peak_label_bounds(day):
    # Centered over the bar, shifted inward at the edges to stay in the margins.
    width = 230
    left = min(max(bar_center(day) - width / 2, 64), 1136 - width)
    return QRectF(left, 0, width, 38)


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


def paint_card(painter, data, branding=True):
    """Draw the card in 1200x1500 card units; the caller sets any scale."""
    ensure_fonts()
    ui = Lines(data['lang']).ui
    painter.fillRect(QRectF(0, 0, CARD_W, CARD_H), QColor(BACKGROUND))
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)

    def text(x, y, width, height, value, size=MIN_FONT, color='#F2EDEA', bold=False,
             align=Qt.AlignLeft, baseline=None):
        font = card_font(data['lang'], size, bold)
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

    def line(y):
        painter.fillRect(64, y, 1072, 1, QColor('#33241F'))

    header = '> SHION / WEEKLY' if data['lang'] == 'en' else '> SHION / ' + ui('weekly_report')
    text(64, 40, 1072, 48, header, 28, ACCENT)
    text(64, 100, 1072, 44, data['start'] + '  —  ' + data['end'], 28, '#9C8A84')
    line(164)
    if data.get('ongoing'):
        text(64, 230, 760, 94, ui('weekly_ongoing', n=data['day_n']), 52, ACCENT, True)
        sprite_name = 'idle'
    else:
        text(64, 200, 760, 94, data['title']['name'], 58, ACCENT, True)
        text(64, 300, 760, 58, data['title']['comment'], 30)
        sprite_name = data['title']['sprite']
    sprite = QImage(str(ROOT / 'assets/sprites' / (sprite_name + '.png')))
    if sprite.isNull():
        sprite = QImage(str(ROOT / 'assets/sprites/idle.png'))
    if not sprite.isNull():
        size = sprite.size().scaled(QSize(260, 240), Qt.KeepAspectRatio)
        painter.drawImage(QRectF(855 + (260 - size.width()) / 2, 184, size.width(), size.height()), sprite)
    line(438)
    totals = data['totals']
    if data['enabled']:
        text(64, 462, 650, 44, ui('weekly_total'), 28, '#9C8A84')
        text(64, 512, 660, 110, number(totals['total_tokens'], data['lang']), 88, ACCENT, True, baseline=604)
        text(760, 462, 376, 44, ui('weekly_output'), 28, '#9C8A84')
        text(760, 540, 376, 80, number(totals['output_tokens'], data['lang']), 50, baseline=604)
        text(64, 630, 560, 44, ui('weekly_price', price=f"{data['price']:.2f}"), 28)
        text(600, 630, 536, 44, ui('weekly_partial' if data['partial'] else 'weekly_estimate'), 28,
             '#9C8A84', align=Qt.AlignRight)
    else:
        text(64, 500, 1072, 80, ui('weekly_disabled'), 36, '#9C8A84')
    if 'seven_day_peak' in totals:
        text(64, 680, 1072, 44, ui('weekly_quota', value=f"{totals['seven_day_peak']:g}"), 28, '#9C8A84')
    if data.get('has_stats', True):
        metrics = [('weekly_tasks', totals['tasks']), ('weekly_hours', f"{totals['seconds'] / 3600:.1f} h"),
                   ('weekly_approvals', totals['approvals']), ('weekly_denials', totals['denials']),
                   ('weekly_pats', totals['pats']), ('weekly_snacks', totals['snacks'])]
        for i, (key, value) in enumerate(metrics):
            x, y = 64 + i % 3 * 365, 748 + i // 3 * 124
            text(x, y, 330, 40, ui(key), 28, '#9C8A84')
            text(x, y + 42, 330, 62, str(value), 40)
    else:
        text(64, 840, 1072, 60, ui('weekly_no_stats'), 32, '#9C8A84')
    line(1006)
    text(64, 1026, 1072, 44, ui('weekly_chart' if data['enabled'] else 'weekly_tasks'), 28, '#9C8A84')
    future = data.get('future') or [False] * 7
    done = [v for v, f in zip(data['daily'], future) if not f]
    peak = max(max(done, default=0), 1)
    peak_day = data.get('peak_day')
    for i, value in enumerate(data['daily']):
        x, center = 85 + i * 153, bar_center(i)
        label = (date.fromisoformat(data['start']) + timedelta(days=i)).strftime('%m-%d')
        if future[i]:
            pen = QPen(QColor('#4A3630'), 2, Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRectF(x + 1, 1161, 93, 118))
            text(center - 70, 1288, 140, 40, label, 28, '#5A4A44', align=Qt.AlignHCenter)
            continue
        height = int(120 * value / peak)
        painter.fillRect(x, 1280 - height, 95, max(height, 2),
                         QColor(ACCENT if i == peak_day else '#5A3A2C'))
        if i == peak_day:
            bounds = peak_label_bounds(i)
            text(bounds.x(), 1280 - height - 78, bounds.width(), bounds.height(),
                 ui('weekly_peak'), 28, ACCENT, align=Qt.AlignHCenter)
        text(center - 70, 1288, 140, 40, label, 28, '#9C8A84', align=Qt.AlignHCenter)
        text(center - 72, 1280 - height - 40, 144, 38, number(value, data['lang']), 28,
             align=Qt.AlignHCenter)
    line(1350)
    text(64, 1362, 1072, 48, ui('weekly_latest', time=data['latest'] or '—'), 28)
    if branding:
        text(64, 1424, 1072, 44, 'github.com/iLLyaaaaaa/shion', 28, '#9C8A84')


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
