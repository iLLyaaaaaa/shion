"""QPainter report card and non-activating weekly report window."""
from pathlib import Path
import os
from datetime import date, timedelta

from PySide6.QtCore import QPointF, QRectF, QStandardPaths, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from shion.lines import Lines

ROOT = Path(__file__).resolve().parents[1]
FONTS = ['Microsoft YaHei', 'Yu Gothic', 'Consolas']


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


def peak_label_bounds(day):
    center = 85 + day * 153 + 95 / 2
    width = min(180, 2 * min(center - 64, 1136 - center))
    return QRectF(center - width / 2, 0, width, 32)


def number(value, lang):
    units = [(1e8, '億' if lang == 'ja' else '亿'), (1e4, '万')] if lang in ('zh', 'ja') else [(1e9, 'B'), (1e6, 'M'), (1e3, 'K')]
    for scale, unit in units:
        if value >= scale:
            return f'{value / scale:.1f}'.rstrip('0').rstrip('.') + unit
    return str(int(value))


def render_card(data, branding=True):
    # Qt's Windows offscreen plugin may expose no system fonts. Read installed
    # fonts for snapshot QA; do not bundle or copy any font files.
    if not QFontDatabase.families():
        directory = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
        for filename in ('msyh.ttc', 'YuGothR.ttc', 'YuGothM.ttc', 'YuGothB.ttc', 'consola.ttf'):
            path = directory / filename
            if path.is_file():
                QFontDatabase.addApplicationFont(str(path))
    ui = Lines(data['lang']).ui
    image = QImage(1200, 1500, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor('#1A1212'))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)

    def text(x, y, width, height, value, size=28, color='#F2EDEA', bold=False,
             align=Qt.AlignLeft, baseline=None):
        font = card_font(data['lang'], size, bold)
        painter.setFont(font)
        painter.setPen(QColor(color))
        # Fit localizations and large counts without clipping or overlap.
        while painter.fontMetrics().horizontalAdvance(value) > width and font.pixelSize() > 16:
            font.setPixelSize(font.pixelSize() - 1)
            painter.setFont(font)
        value = painter.fontMetrics().elidedText(value, Qt.ElideRight, int(width))
        if baseline is not None:
            painter.drawText(QPointF(x, baseline), value)
        else:
            painter.drawText(QRectF(x, y, width, height), align | Qt.AlignVCenter, value)

    def line(y):
        painter.fillRect(64, y, 1072, 1, QColor('#33241F'))

    try:
        header = '> SHION / WEEKLY' if data['lang'] == 'en' else '> SHION / ' + ui('weekly_report')
        text(64, 42, 1072, 46, header, 27, '#F4772E')
        text(64, 102, 1072, 40, data['start'] + '  —  ' + data['end'], 27, '#9C8A84')
        line(164)
        text(64, 200, 720, 94, data['title']['name'], 58, '#F4772E', True)
        text(64, 300, 720, 58, data['title']['comment'], 29)
        sprite = QImage(str(ROOT / 'assets/sprites' / (data['title']['sprite'] + '.png')))
        if sprite.isNull():
            sprite = QImage(str(ROOT / 'assets/sprites/idle.png'))
        if not sprite.isNull():
            scaled = sprite.scaled(260, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            painter.drawImage(855 + (260 - scaled.width()) // 2, 184, scaled)
        line(438)
        totals = data['totals']
        if data['enabled']:
            text(64, 466, 650, 40, ui('weekly_total'), 26, '#9C8A84')
            text(64, 512, 660, 110, number(totals['total_tokens'], data['lang']), 88, '#F4772E', True, baseline=604)
            text(780, 466, 350, 40, ui('weekly_output'), 26, '#9C8A84')
            text(780, 540, 350, 80, number(totals['output_tokens'], data['lang']), 50, baseline=604)
            text(780, 636, 350, 48, ui('weekly_price', price=f"{data['price']:.2f}"), 26)
            text(780, 686, 350, 35, ui('weekly_partial' if data['partial'] else 'weekly_estimate'), 22, '#9C8A84')
        else:
            text(64, 510, 1000, 80, ui('weekly_disabled'), 36, '#9C8A84')
        metrics = [('weekly_tasks', totals['tasks']), ('weekly_hours', f"{totals['seconds'] / 3600:.1f} h"),
                   ('weekly_approvals', totals['approvals']), ('weekly_denials', totals['denials']),
                   ('weekly_pats', totals['pats']), ('weekly_snacks', totals['snacks'])]
        for i, (key, value) in enumerate(metrics):
            x, y = 64 + i % 3 * 365, 754 + i // 3 * 122
            text(x, y, 330, 35, ui(key), 24, '#9C8A84')
            text(x, y + 40, 330, 62, str(value), 40)
        line(1006)
        text(64, 1034, 1072, 40, ui('weekly_chart' if data['enabled'] else 'weekly_tasks'), 26, '#9C8A84')
        peak = max(max(data['daily']), 1)
        peak_day = data['daily'].index(max(data['daily'])) if max(data['daily']) > 0 else None
        for i, value in enumerate(data['daily']):
            x, height = 85 + i * 153, int(120 * value / peak)
            painter.fillRect(x, 1280 - height, 95, max(height, 2),
                             QColor('#F4772E' if i == peak_day else '#5A3A2C'))
            if i == peak_day:
                bounds = peak_label_bounds(i)
                text(bounds.x(), 1280 - height - 77, bounds.width(), bounds.height(),
                     ui('weekly_peak'), 20, '#F4772E', align=Qt.AlignHCenter)
            label = (date.fromisoformat(data['start']) + timedelta(days=i)).strftime('%m-%d')
            text(x - 13, 1288, 135, 38, label, 22, '#9C8A84')
            text(x - 13, 1280 - height - 35, 140, 32, number(value, data['lang']), 20)
        line(1350)
        text(64, 1365, 1050, 45, ui('weekly_latest', time=data['latest'] or '—'), 26)
        if branding:
            text(64, 1430, 1070, 32, 'github.com/iLLyaaaaaa/shion', 21, '#9C8A84')
    finally:
        painter.end()
    return image


class WeeklyWindow(QDialog):
    def __init__(self, data, branding=True):
        # Showing never activates the window; an explicit user click can focus
        # it so the standard QDialog Escape action remains available.
        super().__init__(None, Qt.Tool)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle(Lines(data['lang']).ui('weekly_report'))
        self.data, self.branding = data, branding
        self.image = render_card(data, branding)
        ui = Lines(data['lang']).ui
        layout = QVBoxLayout(self)
        preview = QLabel()
        screen = QApplication.primaryScreen()
        height = min(650, max(240, screen.availableGeometry().height() - 150)) if screen else 600
        preview.setPixmap(QPixmap.fromImage(self.image).scaledToHeight(height, Qt.SmoothTransformation))
        self.preview, self.preview_height = preview, height
        layout.addWidget(preview)
        buttons = QHBoxLayout()
        save = QPushButton(ui('weekly_save'))
        copy = QPushButton(ui('weekly_copy'))
        self.save_button, self.copy_button = save, copy
        save.clicked.connect(self.save_image)
        copy.clicked.connect(lambda: QApplication.clipboard().setImage(self.image))
        buttons.addWidget(save)
        buttons.addWidget(copy)
        layout.addLayout(buttons)
        self.message = QLabel()
        layout.addWidget(self.message)

    def update_report(self, data):
        self.data = data
        ui = Lines(data['lang']).ui
        self.setWindowTitle(ui('weekly_report'))
        self.save_button.setText(ui('weekly_save'))
        self.copy_button.setText(ui('weekly_copy'))
        self.image = render_card(data, self.branding)
        self.preview.setPixmap(QPixmap.fromImage(self.image).scaledToHeight(self.preview_height, Qt.SmoothTransformation))

    def save_image(self):
        folder = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
        default = str(Path(folder) / ('Shion-weekly-' + self.data['start'] + '.png'))
        chosen, _ = QFileDialog.getSaveFileName(self, self.windowTitle(), default, 'PNG (*.png)')
        if chosen:
            ok = self.image.save(chosen, 'PNG')
            self.message.setText(Lines(self.data['lang']).ui('weekly_saved' if ok else 'weekly_failed'))
