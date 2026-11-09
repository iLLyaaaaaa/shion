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
from .head_touch import HeadGesture
from .lift import BodyGesture, SCENE_PADDING, clamp_offset
from .tickle import BellyGesture


FACE_LABELS = ("得意", "平静", "开心", "惊讶", "委屈", "生气", "困倦", "晕乎")


class Canvas(QWidget):
    def __init__(self, rig, settings, scale, seed=7):
        super().__init__()
        self.rig, self.settings, self.display_scale = rig, settings, scale
        self.animator = Animator(settings, seed, now=time.perf_counter())
        self.renderer = Renderer(rig, scale * self.devicePixelRatioF())
        left,top,right,bottom = SCENE_PADDING
        self.setFixedSize(math.ceil((rig.size[0]+left+right)*scale)+24,
                          math.ceil((rig.size[1]+top+bottom)*scale)+24)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.last_tick = time.perf_counter()
        self.paint_times = deque(maxlen=180)
        self.frame_ms = deque(maxlen=180)
        self.measurements = []
        self.measure = False
        self.benchmark_pinch = False
        self.benchmark_head = None
        self.benchmark_lift = False
        self.benchmark_tickle = False
        self.next_benchmark_knock = 0.
        self.head_gesture = HeadGesture()
        self.body_gesture = BodyGesture()
        self.cheek_gesture = BodyGesture()
        self.belly_gesture = BellyGesture()
        self.belly_point = (543.,880.)
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
        elif self.benchmark_head == 'knock' and now >= self.next_benchmark_knock:
            self.animator.knock_head(now=now)
            self.next_benchmark_knock = now+.45
        elif self.benchmark_head == 'pat':
            self.animator.stroke_head(math.cos(now*5), now=now)
        elif self.benchmark_lift:
            if not self.animator.lift.held:self.animator.begin_lift((325,586),now=now,cheek=True)
            x=180*math.sin(now*6)
            self.animator.move_lift((x,-120+50*math.sin(now*3)),x*self.display_scale,now=now)
        elif self.benchmark_tickle:
            self.animator.tickle_belly(now=now)
        if self.head_gesture.active and (self.settings.underlays_only or not (self.settings.knock or self.settings.pat)):
            self.head_gesture.clear()
        if self.body_gesture.active and (self.settings.underlays_only or not self.settings.lift):
            self.body_gesture.clear()
        if self.belly_gesture.active and (self.settings.underlays_only or not self.settings.tickle):
            self.belly_gesture.clear()
            self.animator.release_tickle(now=now)
        self.animator.advance(dt, now=now)
        self.reaction_changed()
        if (not self.animator.dragging and not self.head_gesture.active and not self.body_gesture.active
                and not self.belly_gesture.active and not self.cheek_gesture.active
                and QWidget.mouseGrabber()==self):
            self.releaseMouse()
            self.unsetCursor()
        self.update()

    def paintEvent(self, event):
        start = time.perf_counter()
        scale = self.display_scale * self.devicePixelRatioF()
        if abs(self.renderer.scale - scale) > 1e-6:
            self.renderer = Renderer(self.rig, scale)
        im = self.renderer.render(self.settings, self.animator.pose, padding=SCENE_PADDING)
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#eee9e5"))
        left,top,right,bottom = SCENE_PADDING
        p.drawImage(QRectF(12, 12, (self.rig.size[0]+left+right)*self.display_scale,
                           (self.rig.size[1]+top+bottom)*self.display_scale), im)
        p.end()
        end = time.perf_counter()
        self.paint_times.append(end)
        self.frame_ms.append((end - start) * 1000)
        if self.measure:
            self.measurements.append((end, (end - start) * 1000))

    def point(self, event):
        p = event.position()
        x,y = self.image_origin
        return np.array([(p.x()-x)/self.display_scale, (p.y()-y)/self.display_scale])

    @property
    def image_origin(self):
        return (12+SCENE_PADDING[0]*self.display_scale, 12+SCENE_PADDING[1]*self.display_scale)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = self.point(event)
        hit, local = self.renderer.hit_test(point, self.settings, self.animator.pose, crown=True,
                                          belly=self.settings.tickle)
        if self.animator.lift.held:
            return
        if hit == "cheek":
            self.cheek_gesture.press((event.position().x(),event.position().y()),point,
                                     self.animator.pose.root_offset)
            self.animator.press(local, now=time.perf_counter())
            self.animator.advance(0)
            self.reaction_changed()
            self.update()
            self.grabMouse()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif hit == "crown" and (self.settings.knock or self.settings.pat):
            self.head_gesture.press((event.position().x(), event.position().y()))
            self.grabMouse()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif hit == "head":
            self.animator.impulse(1 if point[0] >= 543 else -1)
        elif hit == 'crown':
            self.animator.impulse(1 if point[0] >= 543 else -1)
        elif hit == 'belly' and not self.settings.underlays_only:
            self.belly_gesture.press((event.position().x(),event.position().y()))
            self.belly_point = tuple(point)
            self.grabMouse()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseDoubleClickEvent(self, event):
        self.mousePressEvent(event)

    def _move_head(self, event):
        delta = self.head_gesture.move((event.position().x(), event.position().y()), self.settings.pat)
        if delta:
            self.animator.stroke_head(delta, now=time.perf_counter())
            self.animator.advance(0)
            self.reaction_changed()
            self.update()

    def mouseMoveEvent(self, event):
        point=self.point(event)
        if self.belly_gesture.active:
            self._move_belly(event)
        elif self.body_gesture.active:
            self._move_body(event)
        elif self.head_gesture.active:
            self._move_head(event)
        elif self.cheek_gesture.active:
            self._move_cheek(event)
        else:
            hit,_=self.renderer.hit_test(point,self.settings,self.animator.pose,crown=True,
                                         belly=self.settings.tickle)
            if (hit=='cheek' or (hit=='crown' and (self.settings.knock or self.settings.pat))
                    or hit=='belly'):
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:self.unsetCursor()

    def _move_belly(self, event):
        now = time.perf_counter()
        logical = (event.position().x(),event.position().y())
        action = self.belly_gesture.move(logical,now)
        if action == 'tickle':
            self.animator.tickle_belly(now=now)
        elif action == 'pause':
            self.animator.release_tickle(now=now)
        if action:
            self.animator.advance(0)
            self.reaction_changed()
            self.update()

    def _move_cheek(self, event):
        now = time.perf_counter()
        logical = (event.position().x(),event.position().y())
        dx = logical[0]-self.cheek_gesture.origin[0]
        up = self.cheek_gesture.origin[1]-logical[1]
        point = self.renderer.rig_point(self.point(event),self.animator.pose)
        local = self.renderer.head_surface.source_point(point,self.animator.pose,allow_outside=True)
        if local is not None:self.animator.drag(local)
        if self.settings.lift and up > 12. and up > abs(dx)*1.2:
            self.animator.advance(0)
            self.animator.begin_lift(point,now=now,cheek=True)
            self.body_gesture.press(logical,self.point(event),self.animator.pose.root_offset)
            self.body_gesture.started = True
            self.cheek_gesture.clear()
            self.animator.advance(0)
            self.reaction_changed()
            self.update()

    def _move_body(self, event):
        was_started = self.body_gesture.started
        if not self.body_gesture.move((event.position().x(),event.position().y())):
            return
        now = time.perf_counter()
        if not was_started:
            pivot = self.renderer.rig_point(self.body_gesture.point,self.animator.pose)
            self.body_gesture.offset = tuple(self.animator.pose.root_offset)
            self.animator.begin_lift(pivot,now=now)
        offset = clamp_offset(np.array(self.body_gesture.offset)+self.point(event)-self.body_gesture.point)
        self.animator.move_lift(tuple(offset), (offset[0]-self.body_gesture.offset[0])*self.display_scale,
                                now=now)
        self.animator.advance(0)
        self.reaction_changed()
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.cheek_gesture.active:
                self._move_cheek(event)
                self.cheek_gesture.clear()
                if self.body_gesture.active:
                    self.animator.release_lift(now=time.perf_counter())
                    self.body_gesture.clear()
                else:self.animator.release(now=time.perf_counter())
                self.animator.advance(0)
                self.reaction_changed()
                self.update()
            elif self.belly_gesture.active:
                self._move_belly(event)
                self.belly_gesture.clear()
                self.animator.release_tickle(now=time.perf_counter())
                if self.body_gesture.active:
                    self.animator.release_lift(now=time.perf_counter())
                    self.body_gesture.clear()
                self.animator.advance(0)
                self.reaction_changed()
                self.update()
            elif self.body_gesture.active:
                self._move_body(event)
                self.animator.release_lift(now=time.perf_counter())
                self.body_gesture.clear()
                self.animator.advance(0)
                self.reaction_changed()
                self.update()
            elif self.head_gesture.active:
                self._move_head(event)
                if self.head_gesture.release():
                    direction = 1 if self.point(event)[0] >= self.rig.pivots['neck'][0] else -1
                    if self.settings.knock:self.animator.knock_head(direction, now=time.perf_counter(),
                                                                    point=tuple(self.point(event)))
                    else:self.animator.impulse(direction)
                else:
                    self.animator.release_head(now=time.perf_counter())
                self.animator.advance(0)
                self.reaction_changed()
                self.update()
            else:
                self.animator.release(now=time.perf_counter())
            if QWidget.mouseGrabber()==self:self.releaseMouse()
            self.unsetCursor()

    def focusOutEvent(self, event):
        self.cheek_gesture.clear()
        self.head_gesture.clear()
        self.body_gesture.clear()
        self.belly_gesture.clear()
        self.animator.release_tickle(now=time.perf_counter())
        self.animator.release_lift(now=time.perf_counter())
        self.animator.release_head(now=time.perf_counter())
        self.animator.release(now=time.perf_counter())
        if QWidget.mouseGrabber()==self:self.releaseMouse()
        self.unsetCursor()
        super().focusOutEvent(event)


class Preview(QWidget):
    def __init__(self, rig: Rig, settings: Settings, scale=0.4, seed=7):
        super().__init__()
        source=rig.data.get('manual_source_set',{}).get('name','去粉线版')
        suffix=" · 被捏反应" if rig.cheek_config else ""
        self.setWindowTitle(f"诗音 V3 · 脸颊拎起 / 挠痒 · {source}{suffix}")
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
        for key, label in (("breath", "呼吸"), ("blink", "眨眼"), ("sway", "头发摆动"),
                           ("pinch", "麻薯捏脸"), ("knock", "敲头"), ("pat", "摸头"),
                           ("lift", "拎起 / 拖动"), ("tickle", "肚子挠痒")):
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
            elif key == "pinch":
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
        head_toggle = QToolButton()
        head_toggle.setText("敲头 / 摸头参数（展开）")
        head_toggle.setCheckable(True)
        head_box = QWidget()
        head_form = QFormLayout(head_box)
        for key, label, low, high, step in (
            ('head_drop','整头下沉 px',0,60,2),
            ('knock_hold','敲后委屈保持 s',.1,3,.1),
            ('knock_gap','连敲间隔 s',.2,3,.1),
            ('knock_count','连敲加长次数',2,8,1),
            ('protest','连敲委屈保持 s',0,5,.1),
            ('tilt','摸头倾角 °',0,5,.25),
            ('return_time','回正时间 s',.1,1,.05),
            ('after_hold','开心余韵 s',0,5,.1),
            ('fade','恢复淡入 s',0,2,.05)):
            spin = QDoubleSpinBox()
            spin.setDecimals(0 if key=='knock_count' else 3)
            spin.setRange(low, high)
            spin.setSingleStep(step)
            spin.setValue(getattr(settings.head_touch, key))
            spin.valueChanged.connect(lambda v,k=key:self.change_head(k,v))
            head_form.addRow(label, spin)
            self.controls.append((spin,'head_touch.'+key,1))
        head_box.setVisible(False)
        head_toggle.toggled.connect(head_box.setVisible)
        panel.addWidget(head_toggle)
        panel.addWidget(head_box)
        self.head_label = QLabel("敲摸反应：等待触碰头顶")
        self.head_label.setWordWrap(True)
        panel.addWidget(self.head_label)
        self.reaction_label = QLabel("被捏反应：等待抓取")
        self.reaction_label.setWordWrap(True)
        panel.addWidget(self.reaction_label)
        self.lift_label = QLabel('拎起反应：向上提左脸颊')
        self.lift_label.setWordWrap(True)
        panel.addWidget(self.lift_label)
        self.tickle_label = QLabel('挠痒反应：在肚子来回揉动')
        self.tickle_label.setWordWrap(True)
        panel.addWidget(self.tickle_label)
        self.canvas.reaction_changed = self.update_reaction
        reset = QPushButton("恢复默认")
        reset.clicked.connect(self.reset)
        panel.addWidget(reset)
        hint = QLabel("只有左侧突出的脸颊可以拎起。\n左右拉是捏脸；向上提超过 12px 拎起。\n拖动时保持脸颊拉伸，松手才回弹。\n肚子来回揉动挠痒；其他身体不拎起。")
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
        if key in ('knock','pat','underlays_only'):
            self.canvas.head_gesture.clear()
            self.canvas.animator.release_head(now=time.perf_counter())
        if key in ('lift','underlays_only'):
            self.canvas.body_gesture.clear()
            self.canvas.animator.release_lift(now=time.perf_counter())
        if key in ('tickle','underlays_only'):
            self.canvas.belly_gesture.clear()
            self.canvas.animator.release_tickle(now=time.perf_counter())
        self.canvas.animator.advance(0)
        self.update_reaction()
        self.canvas.update()

    def change_reaction(self,key,value):
        self.settings.reaction = replace(self.settings.reaction,**{key:value})

    def change_head(self, key, value):
        if key == 'knock_count':value = int(value)
        self.settings.head_touch = replace(self.settings.head_touch, **{key:value})

    def update_reaction(self):
        r=self.canvas.animator.reaction
        self.combo.setEnabled(not self.canvas.animator.interaction_active)
        labels={'idle':'等待抓取','surprise':'惊讶','struggle':'挣扎','cry':'委屈',
                'rebound':'回弹','hold':'余韵','fade':'恢复原表情'}
        suffix=f" · 本次窗口内第 {r.count} 次" if r.active else ''
        if r.easter:suffix+=' · 连捏彩蛋'
        self.reaction_label.setText('被捏反应：'+labels[r.stage]+suffix)
        h = self.canvas.animator.head_touch
        head_labels = {'idle':'等待触碰头顶','knock':'轻敲 · 委屈冒金星','protest':'连敲 · 委屈',
                       'pat':'摸头 · 开心','fade':'恢复原表情'}
        self.head_label.setText('敲摸反应：'+head_labels[h.stage]+(f' · 连敲 {h.count} 次' if h.count else ''))
        l = self.canvas.animator.lift
        lift_labels = {'idle':'向上提左脸颊','held':'拎起 · 随手移动','return':'回原站位 · 回弹',
                       'hold':'落稳余韵','fade':'恢复原表情'}
        self.lift_label.setText('拎起反应：'+lift_labels[l.stage]+(' · 晃晕了' if l.dizzy else ''))
        t = self.canvas.animator.tickle
        tickle_labels = {'idle':'在肚子来回揉动','tickle':'开心躲闪','settle':'慢慢平静',
                         'hold':'开心余韵','fade':'恢复原表情'}
        self.tickle_label.setText('挠痒反应：'+tickle_labels[t.stage])

    def expression_changed(self):
        self.change("expression", self.combo.currentData())

    def reset(self):
        original=self.canvas.animator.original_expression if self.canvas.animator.interaction_active else None
        defaults = Settings()
        for widget, key, factor in self.controls:
            value = (getattr(getattr(defaults,key.split('.')[0]),key.split('.')[1])
                     if '.' in key else getattr(defaults, key))
            if isinstance(widget, QCheckBox):
                widget.setChecked(value)
            elif isinstance(widget,QDoubleSpinBox):
                widget.setValue(value)
            else:
                widget.setValue(round(value * factor))
        self.combo.setCurrentIndex(self.combo.findData(original) if original is not None else 0)
        self.canvas.animator = Animator(self.settings, self.seed, now=time.perf_counter())
        self.canvas.head_gesture.clear()
        self.canvas.body_gesture.clear()
        self.canvas.cheek_gesture.clear()
        self.canvas.belly_gesture.clear()
        if QWidget.mouseGrabber()==self.canvas:self.canvas.releaseMouse()
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


def benchmark(window, seconds, output, app, pinch=False, head=None, lift=False, tickle=False):
    """Count paintEvent completions, not timer callbacks; exclude warm-up."""
    window.canvas.benchmark_pinch = pinch
    window.canvas.benchmark_head = head
    window.canvas.benchmark_lift = lift
    window.canvas.benchmark_tickle = tickle
    def start():
        window.canvas.measure = True
        QTimer.singleShot(round(seconds * 1000), finish)

    def finish():
        rows = window.canvas.measurements
        times = np.array([r[0] for r in rows])
        ms = np.array([r[1] for r in rows])
        result = {"platform": app.platformName(), "scale": window.canvas.display_scale,
                  "device_pixel_ratio": window.canvas.devicePixelRatioF(), "pinch": pinch, "head":head,
                  "lift":lift,"tickle":tickle,
                  "frames": len(rows), "fps": float((len(rows) - 1) / (times[-1] - times[0])),
                  "render_ms_p50": float(np.median(ms)), "render_ms_p95": float(np.percentile(ms, 95)),
                  "frame_interval_ms_p95": float(np.percentile(np.diff(times) * 1000, 95))}
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result))
        window.close()
        app.quit()
    QTimer.singleShot(2000, start)
