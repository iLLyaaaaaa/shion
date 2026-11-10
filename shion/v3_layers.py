"""V3 两条渲染路径与待机头发的间歇轻摆。

- 仿射路径：头发静止、没有捏脸形变、没有反应脸和金星时，头部用缓存帧整张平移/旋转，
  身体照旧用 QPainter 画刚体部件；不跑网格变形。
- 网格路径：其余情况，交给原型的 Renderer.render。

头部是一整张合成图（头发、脸、刘海在同一张里），头发摆动靠共用的平滑位移场，
所以“头发在动”只能走网格路径。待机时头发改为间歇轻摆：大多数时间静止。
"""
from __future__ import annotations

import random
from collections import OrderedDict

ANGLE_THRESHOLD = 0.05  # 度；与 HeadSurface 的 round(angle*10) 一致


def hair_still(pose) -> bool:
    return not any(round(v * 10) for v in pose.angles.values())


def affine_ok(pose) -> bool:
    return (hair_still(pose) and not any(pose.pinch_delta)
            and pose.reaction_face is None and not pose.star_effects)


def render_affine(renderer, settings, pose):
    """与网格路径同一位置、同一种双线性采样；只是不做网格变形。"""
    return _render_rotated(renderer, settings, pose)


# 纯平移时 Qt 会走整数像素快速拷贝，小数位移被吞掉（呼吸会一格一格跳）。
# 给一个看不出的极小旋转，强制走双线性采样。
MIN_ROLL = 1e-4  # 度


def _render_rotated(renderer, settings, pose):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QImage, QPainter
    from v3proto.lift import root_matrix
    from v3proto.motion import translation
    surface = renderer.head_surface
    scale = renderer.scale
    body = renderer._body_frame(settings, pose)
    head = _head_image(surface, settings, pose)
    neck = renderer.rig.pivots["neck"]
    rx, ry = (neck[0] - surface.x) * scale, (neck[1] - surface.y) * scale
    painter = QPainter(body)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.translate((surface.x + pose.head_x) * scale, (surface.y + pose.head_y) * scale)
    painter.translate(rx, ry)
    painter.rotate(pose.head_roll or MIN_ROLL)
    painter.translate(-rx, -ry)
    painter.drawImage(QPointF(0, 0), head)
    painter.end()
    if any(pose.root_offset) or pose.root_roll:
        scene = QImage(body.width(), body.height(), body.format())
        scene.fill(0)
        painter = QPainter(scene)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        renderer._draw(painter, body, 0, 0, translation(0, 0) @ root_matrix(pose))
        painter.end()
        body = scene
    return body


# 仿射路径用的 QImage 副本：只是转换结果，未命中时转一次约 0.1ms；64 份会让头部帧内存翻倍（S7）
QFRAME_LIMIT = 8


def _head_image(surface, settings, pose):
    """头部缓存帧（预乘数组）对应的 QImage；数组换了就重建。"""
    from v3proto.render import from_premultiplied
    pixels = surface.compose(settings, pose)
    cache = surface.__dict__.setdefault("_v3_qframes", OrderedDict())
    key = (settings.expression, round(pose.eye_scale, 5))
    entry = cache.get(key)
    if entry is None or entry[0] is not pixels:
        entry = (pixels, from_premultiplied(pixels))
        cache[key] = entry
        while len(cache) > QFRAME_LIMIT:
            cache.popitem(last=False)
    cache.move_to_end(key)
    return entry[1]


# ---- 待机头发间歇轻摆 ----
FADE = 0.6       # 秒：淡入 / 淡出
EPISODE = 2.5    # 秒：一次轻摆总长
REST = (6.0, 12.0)  # 秒：两次轻摆之间


def _smooth(u: float) -> float:
    u = min(1.0, max(0.0, u))
    return u * u * (3 - 2 * u)


class SwayEnvelope:
    """0～1 的包络，乘到 Settings.sway_degrees 上（同时缩放目标角和上限）。"""

    def __init__(self, now: float, seed: int | None = None):
        self.rng = random.Random(seed)
        self.start = now + self.rng.uniform(*REST)
        self.end = self.start + EPISODE

    def value(self, now: float) -> float:
        if now >= self.end:
            self.start = self.end + self.rng.uniform(*REST)
            self.end = self.start + EPISODE
        if now < self.start:
            return 0.0
        return min(_smooth((now - self.start) / FADE), _smooth((self.end - now) / FADE))

    def force(self, now: float) -> None:
        """互动中：立刻满幅，结束后 FADE 秒内淡出。"""
        self.value(now)  # 先翻到当前这一轮
        self.start = min(self.start, now - FADE)
        self.end = max(self.end, now + 2 * FADE)

    def until_start(self, now: float) -> float:
        """距下一次轻摆开始还有多少秒（正在摆时为 0）。"""
        return max(0.0, self.start - now)


__all__ = ["affine_ok", "hair_still", "render_affine", "SwayEnvelope", "ANGLE_THRESHOLD"]
