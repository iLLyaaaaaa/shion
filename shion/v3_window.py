"""用 V3 纸偶显示的桌宠窗口（源码入口 --renderer v3，默认仍是 V2）。

窗口属性、状态机接口、V2 程序动画帧（压扁、倾斜、跳跃）、拖动/下落/夹边和
所有信号都沿用 PetWindow；这里只换“画什么”。S1 交互仍走 V2 手势规则。
"""
from __future__ import annotations

import math
from collections import OrderedDict

import numpy as np
from PySide6.QtCore import QPointF
from PySide6.QtGui import QGuiApplication, QImage, QPainter

from shion.pet_window import MARGIN_BOTTOM, MARGIN_X, MARGIN_TOP, PetWindow
from shion.v3_display import V2_FOOT_GAP_RATIO, expression_for, logical_scale

RENDERER_CACHE = 2
SIDE_PADDING = 48  # rig 像素：头发摆动、倾斜时不被裁掉

_RIGS: dict[str, object] = {}


def shared_rig(side: str = "left"):
    """进程内每侧只加载一次 rig（约 0.3 秒）。"""
    if side not in _RIGS:
        from v3proto.render import Rig
        rig = Rig(cheek_side=side)
        alpha = np.asarray(rig.rest("neutral"))[..., 3]
        ys, xs = np.nonzero(alpha)
        hips = (rig.pivots["hip_l"][0] + rig.pivots["hip_r"][0]) / 2
        rig.v3_visible = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
        rig.v3_foot = (float(hips), float(ys.max()) + 1)
        _RIGS[side] = rig
    return _RIGS[side]


class V3PetWindow(PetWindow):
    renderer_name = "v3"

    # ---- 尺寸与渲染器 ----
    def _v3_setup(self) -> None:
        if getattr(self, "_v3_ready", False):
            return
        from v3proto.animation import Animator, Settings
        self._v3_rig = shared_rig("left")
        self._v3_renderers: OrderedDict[tuple, object] = OrderedDict()
        # S1 只显示；V3 手势在 S3/S4 接入，先关掉以免和 V2 手势重复。
        self._v3_settings = Settings(expression="neutral", pinch=False, knock=False,
                                     pat=False, lift=False, tickle=False)
        self._v3_animator = Animator(self._v3_settings)
        self._v3_clock: float | None = None
        self._v3_image: QImage | None = None
        self._v3_ready = True

    def _load_sprites(self) -> None:
        self._v3_setup()
        screen = QGuiApplication.primaryScreen()
        dpr = self._pixel_ratio or (screen.devicePixelRatio() if screen else 1.0)
        rig = self._v3_rig
        x0, y0, x1, y1 = rig.v3_visible
        foot_x, _ = rig.v3_foot
        self._v3_dpr = dpr
        self._v3_scale = logical_scale(self._height, y1 - y0)
        half = max(foot_x - x0, x1 - foot_x) + SIDE_PADDING
        self._sw = math.ceil(2 * half * self._v3_scale)
        self._sh = self._height
        self.normal_width = self._sw
        self._pixmaps.clear()
        self._sequences.clear()
        self._v3_renderer = self._renderer_for(self._height, dpr)
        self._v3_image = None

    def _renderer_for(self, height: int, dpr: float):
        key = (height, round(dpr, 4))
        if key in self._v3_renderers:
            self._v3_renderers.move_to_end(key)
            return self._v3_renderers[key]
        from v3proto.render import Renderer
        renderer = Renderer(self._v3_rig, self._v3_scale * dpr)
        self._v3_renderers[key] = renderer
        while len(self._v3_renderers) > RENDERER_CACHE:
            self._v3_renderers.popitem(last=False)
        return renderer

    @property
    def v3_texture_scale(self) -> float:
        """设备像素 / rig 像素。"""
        return self._v3_scale * self._v3_dpr

    @property
    def v3_expression(self) -> str:
        return self._v3_settings.expression

    # ---- 每帧 ----
    def _refresh(self, now: float) -> None:
        self._animator.idle_enabled = not (self.motion_active or self._dragging or self._falling
                                          or self.is_pressed or self._drag_playback is not None)
        f = self._animator.frame(now)
        f = self._action_frame(now, f)
        f = self._blend_action(now, f)
        shown = max(f.layers, key=lambda item: item[1])[0] if f.layers else f.sprite
        self._v3_settings.expression = expression_for(shown, self.sprite_name)
        dt = 0.0 if self._v3_clock is None else max(0.0, now - self._v3_clock)
        self._v3_clock = now
        pose = self._v3_animator.advance(dt)
        image = self._v3_renderer.render(self._v3_settings, pose)
        image.setDevicePixelRatio(self._v3_dpr)
        self._v3_image = image
        self._sync_sleep_z(now, f)
        self._frame = f
        old_key = self._mask_key
        region = self._mask_for(f)
        if self._mask_key != old_key:
            self.setMask(region)
        self.update()
        if self._fps_overlay is not None:
            self._fps_overlay.follow()
        if self._pause_badge is not None:
            self._pause_badge.follow()

    def _draw_sprite(self, p: QPainter, f) -> None:
        if self._v3_image is None:
            return
        rig = self._v3_rig
        foot_x, foot_y = rig.v3_foot
        s = self._v3_scale
        p.save()
        p.translate(self.width() / 2, self.height() - MARGIN_BOTTOM - self._jump_offset)
        p.rotate(f.angle)
        p.scale(f.sx, f.sy)
        gap = self._height * V2_FOOT_GAP_RATIO
        p.drawImage(QPointF(-foot_x * s, -gap - foot_y * s), self._v3_image)
        p.restore()


__all__ = ["V3PetWindow", "shared_rig", "MARGIN_X", "MARGIN_TOP"]
