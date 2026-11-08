"""Preview UI and measured paint timings."""
from collections import deque
from dataclasses import replace
import json
import math
import os
from pathlib import Path
import time

import numpy as np
from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QColor, QPainter, QFont, QFontDatabase
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel,
                               QPushButton, QSlider, QVBoxLayout, QWidget, QDoubleSpinBox, QToolButton, QScrollArea)

from .animation import Animator, Settings
from .render import Renderer, Rig


FACE_LABELS = ("得意", "平静", "开心", "惊讶", "委屈", "生气", "困倦", "晕乎")


class Canvas(QWidget):
    def __init__(self, rig, settings, scale, seed=7):
        super().__init__()
        self.rig, self.settings, self.display_scale = rig, settings, scale
        self.animator = Animator(settings, seed, now=time.perf_counter())
        self.renderer = Renderer(rig, scale * self.devicePixelRatioF())
        self.setFixedSize(math.ceil(rig.size[0] * scale) + 24, math.ceil(rig.size[1] * scale) + 24)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.last_tick = time.perf_counter()
        self.paint_times = deque(maxlen=180)
        self.frame_ms = deque(maxlen=180)
        self.measurements = []
        self.measure = False
        self.benchmark_pinch = False
        self.reaction_changed = lambda: None
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.tick)
        # Keep a steady precise timer. Restarting a single-shot deadline timer
        # every frame caused alternating short/long wakeups on Windows.
        self.timer.start(16)

    def tick(self):
        now = time.perf_counter()
        dt = min(0.1, now - self.last_tick)
        self.last_tick = now
        if self.benchmark_pinch:
            if not self.animator.dragging:self.animator.press((325,610), now=now)
            self.animator.delta = np.array([-self.settings.pinch_maximum * (.5+.5*math.sin(self.animator.time * 2)), 0.])
        self.animator.advance(dt, now=now)
        self.reaction_changed()
        if not self.animator.dragging and QWidget.mouseGrabber()==self:
            self.releaseMouse()
            self.unsetCursor()
        self.update()

    def paintEvent(self, event):
        start = time.perf_counter()
        scale = self.display_scale * self.devicePixelRatioF()
        if abs(self.renderer.scale - scale) > 1e-6:
            self.renderer = Renderer(self.rig, scale)
        im = self.renderer.render(self.settings, self.animator.pose)
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#eee9e5"))
        p.drawImage(QRectF(12, 12, self.rig.size[0] * self.display_scale,
                           self.rig.size[1] * self.display_scale), im)
        p.end()
        end = time.perf_counter()
        self.paint_times.append(end)
        self.frame_ms.append((end - start) * 1000)
        if self.measure:
            self.measurements.append((end, (end - start) * 1000))

    def point(self, event):
        p = event.position()
        return np.array([(p.x() - 12) / self.display_scale, (p.y() - 12) / self.display_scale])

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = self.point(event)
        hit, local = self.renderer.hit_test(point, self.settings, self.animator.pose)
        if hit == "cheek":
            self.animator.press(local, now=time.perf_counter())
            self.animator.advance(0)
            self.reaction_changed()
            self.update()
            self.grabMouse()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif hit == "head":
            self.animator.impulse(1 if point[0] >= 543 else -1)

    def mouseMoveEvent(self, event):
        point=self.point(event)
        if self.animator.dragging:
            local=self.renderer.head_surface.source_point(point,self.animator.pose,allow_outside=True)
            if local is not None:self.animator.drag(local)
        else:
            hit,_=self.renderer.hit_test(point,self.settings,self.animator.pose)
            if hit=='cheek':self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:self.unsetCursor()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.animator.release(now=time.perf_counter())
            if QWidget.mouseGrabber()==self:self.releaseMouse()
            self.unsetCursor()

    def focusOutEvent(self, event):
        self.animator.release(now=time.perf_counter())
        if QWidget.mouseGrabber()==self:self.releaseMouse()
        self.unsetCursor()
        super().focusOutEvent(event)


class Preview(QWidget):
    def __init__(self, rig: Rig, settings: Settings, scale=0.4, seed=7):
        super().__init__()
        source=rig.data.get('manual_source_set',{}).get('name','去粉线版')
        suffix=" · 被捏反应" if rig.cheek_config else ""
        self.setWindowTitle(f"诗音 V3 · 动起来的原型 · {source}{suffix}")
        if "Microsoft YaHei" not in QFontDatabase.families():
            font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc"
            if font.exists():
                QFontDatabase.addApplicationFont(str(font))
        self.setFont(QFont("Microsoft YaHei", 9))
        self.settings, self.seed = settings, seed
        self.canvas = Canvas(rig, settings, scale, seed)
        self.controls = []
        layout = QHBoxLayout(self)
        layout.addWidget(self.canvas)
        panel = QVBoxLayout()
        title = QLabel("V3 动作实验台")
        title.setStyleSheet("font-size: 20px; font-weight: bold")
        panel.addWidget(title)
        self.combo = QComboBox()
        for face, label in zip(rig.faces, FACE_LABELS):
            self.combo.addItem(f"{label} / {face}", face)
        self.combo.setCurrentIndex(rig.faces.index(settings.expression))
        self.combo.currentIndexChanged.connect(self.expression_changed)
        panel.addWidget(self.combo)
        self.form = QFormLayout()
        panel.addLayout(self.form)
        for key, label in (("breath", "呼吸"), ("blink", "眨眼"), ("sway", "头发摆动"), ("pinch", "麻薯捏脸")):
            check = QCheckBox(label)
            check.setChecked(getattr(settings, key))
            check.toggled.connect(lambda value, k=key: self.change(k, value))
            self.form.addRow(check)
            self.controls.append((check, key, 1))
            if key == "breath":
                self.slider("breath_amount", "呼吸幅度 %", 0, 100, 100)
            elif key == "blink":
                self.slider("blink_amount", "闭眼深度 %", 0, 100, 100)
            elif key == "sway":
                self.slider("sway_degrees", "摆幅 °", 0, 30, 10)
            else:
                self.slider("pinch_maximum", "拖伸上限 px", 20, 200, 1)
                self.slider("pinch_radius", "高斯半径 px", 60, 160, 1)
        under = QCheckBox("只看垫底")
        under.setChecked(settings.underlays_only)
        under.toggled.connect(lambda v: self.change("underlays_only", v))
        self.controls.append((under, "underlays_only", 1))
        panel.addWidget(under)
        toggle = QToolButton()
        toggle.setText("被捏反应参数（展开）")
        toggle.setCheckable(True)
        panel.addWidget(toggle)
        reaction_box = QWidget()
        reaction_form = QFormLayout(reaction_box)
        for key, label, low, high, step in (
            ('surprise','惊讶时间 s',0,1,.05),
            ('cry_after','持续多久委屈 s',.2,10,.1),
            ('cry_fraction','委屈拉伸比例',.1,1,.05),
            ('rebound_time','回弹时间倍率',.25,3,.1),
            ('after_hold','回弹后保持 s',0,5,.1),
            ('fade','恢复淡入 s',0,2,.05),
            ('combo_window','连捏计数窗口 s',1,30,1),
            ('arm_hz','挣扎速度 Hz',1,10,.5),
            ('arm_degrees','挣扎摆幅 °',0,8,.5),
            ('cry_arm_hz','委屈速度 Hz',1,12,.5),
            ('cry_arm_degrees','委屈摆幅 °',0,8,.5)):
            spin = QDoubleSpinBox()
            spin.setDecimals(2)
            spin.setRange(low,high)
            spin.setSingleStep(step)
            spin.setValue(getattr(settings.reaction,key))
            spin.valueChanged.connect(lambda v,k=key:self.change_reaction(k,v))
            reaction_form.addRow(label,spin)
            self.controls.append((spin,'reaction.'+key,1))
        reaction_box.setVisible(False)
        toggle.toggled.connect(reaction_box.setVisible)
        panel.addWidget(reaction_box)
        self.reaction_label = QLabel("被捏反应：等待抓取")
        self.reaction_label.setWordWrap(True)
        panel.addWidget(self.reaction_label)
        self.canvas.reaction_changed = self.update_reaction
        reset = QPushButton("恢复默认")
        reset.clicked.connect(self.reset)
        panel.addWidget(reset)
        hint = QLabel("按住左侧鼓脸颊向外拉，松手回弹。\n惊讶 → 挣扎 → 委屈；松手后恢复原表情。\n点击头发可轻轻拨动。\n滑条 px 均为原图像素。")
        hint.setWordWrap(True)
        panel.addWidget(hint)
        self.fps_label = QLabel("FPS —")
        panel.addWidget(self.fps_label)
        panel.addStretch()
        panel_widget=QWidget()
        panel_widget.setLayout(panel)
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel_widget)
        scroll.setMinimumWidth(310)
        layout.addWidget(scroll)
        self.stats_timer = QTimer(self)
        self.stats_timer.timeout.connect(self.update_stats)
        self.stats_timer.start(500)

    def slider(self, key, label, low, high, factor):
        box = QHBoxLayout()
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(low, high)
        slider.setValue(round(getattr(self.settings, key) * factor))
        slider.setMinimumWidth(140)
        display = lambda v: f"{v / factor:.1f}" if factor == 10 else str(v)
        value = QLabel(display(slider.value()))
        value.setMinimumWidth(32)
        slider.valueChanged.connect(lambda v: value.setText(display(v)))
        slider.valueChanged.connect(lambda v: self.change(key, v / factor))
        box.addWidget(slider)
        box.addWidget(value)
        self.form.addRow(label, box)
        self.controls.append((slider, key, factor))

    def change(self, key, value):
        setattr(self.settings, key, value)
        self.canvas.animator.advance(0)
        self.update_reaction()
        self.canvas.update()

    def change_reaction(self,key,value):
        self.settings.reaction = replace(self.settings.reaction,**{key:value})

    def update_reaction(self):
        r=self.canvas.animator.reaction
        self.combo.setEnabled(not r.active)
        labels={'idle':'等待抓取','surprise':'惊讶','struggle':'挣扎','cry':'委屈',
                'rebound':'回弹','hold':'余韵','fade':'恢复原表情'}
        suffix=f" · 本次窗口内第 {r.count} 次" if r.active else ''
        if r.easter:suffix+=' · 连捏彩蛋'
        self.reaction_label.setText('被捏反应：'+labels[r.stage]+suffix)

    def expression_changed(self):
        self.change("expression", self.combo.currentData())

    def reset(self):
        original=self.canvas.animator.reaction.base
        defaults = Settings()
        for widget, key, factor in self.controls:
            value = getattr(defaults.reaction,key.split(".")[1]) if key.startswith("reaction.") else getattr(defaults, key)
            if isinstance(widget, QCheckBox):
                widget.setChecked(value)
            elif isinstance(widget,QDoubleSpinBox):
                widget.setValue(value)
            else:
                widget.setValue(round(value * factor))
        self.combo.setCurrentIndex(self.combo.findData(original) if original is not None else 0)
        self.canvas.animator = Animator(self.settings, self.seed, now=time.perf_counter())
        self.update_reaction()
        self.canvas.update()

    def update_stats(self):
        times = self.canvas.paint_times
        if len(times) > 1 and times[-1] > times[0]:
            fps = (len(times) - 1) / (times[-1] - times[0])
            p95 = np.percentile(self.canvas.frame_ms, 95)
            self.fps_label.setText(f"FPS {fps:.1f} · 绘制 P95 {p95:.1f} ms")

    def closeEvent(self, event):
        self.canvas.timer.stop()
        self.stats_timer.stop()
        super().closeEvent(event)


def benchmark(window, seconds, output, app, pinch=False):
    """Count paintEvent completions, not timer callbacks; exclude warm-up."""
    window.canvas.benchmark_pinch = pinch
    def start():
        window.canvas.measure = True
        QTimer.singleShot(round(seconds * 1000), finish)

    def finish():
        rows = window.canvas.measurements
        times = np.array([r[0] for r in rows])
        ms = np.array([r[1] for r in rows])
        result = {"platform": app.platformName(), "scale": window.canvas.display_scale,
                  "device_pixel_ratio": window.canvas.devicePixelRatioF(), "pinch": pinch,
                  "frames": len(rows), "fps": float((len(rows) - 1) / (times[-1] - times[0])),
                  "render_ms_p50": float(np.median(ms)), "render_ms_p95": float(np.percentile(ms, 95)),
                  "frame_interval_ms_p95": float(np.percentile(np.diff(times) * 1000, 95))}
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result))
        window.close()
        app.quit()
    QTimer.singleShot(2000, start)
