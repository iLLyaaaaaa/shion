"""V3 头部帧的眨眼量化与后台预热。

头部整张合成（所有头发层 + 脸 + LANCZOS 缩放）一次约 45ms。眼睛开合度若是
连续值，每次眨眼的每一帧都命中不了缓存。这里：
- 把开合度量化到 0.05 一档（0.1～1 共 19 档）；
- 在一个后台线程里提前合成各表情的睁眼帧、当前表情的全部眨眼档；
- 结果只在主线程放进 HeadSurface.frames（缓存本身不跨线程写）。
"""
from __future__ import annotations

import queue
import sys
import threading
from concurrent.futures import Future
from dataclasses import replace

EYE_STEP = 0.05
CHEEK_KEY = "cheek-prepare"  # pending/requested 里捏脸素材任务的键前缀
EYE_MIN = 0.1


def quantize_eye(eye_scale: float) -> float:
    if eye_scale >= 1.0:
        return 1.0
    q = round(round(eye_scale / EYE_STEP) * EYE_STEP, 2)
    return max(EYE_MIN, min(1.0, q))


BLINK_LEVELS = tuple(sorted({quantize_eye(EYE_MIN + i * EYE_STEP) for i in range(19)} | {1.0}))


def build_frame(surface, settings, eye_scale: float):
    """与 HeadSurface.compose 未命中时完全相同的生成路径。"""
    from PIL import Image
    from v3proto.animation import Pose
    from v3proto.render import premultiplied, qimage
    full = surface._compose_image(settings, Pose(eye_scale=eye_scale))
    return premultiplied(qimage(full.resize((surface.w, surface.h), Image.Resampling.LANCZOS)))


class _BackgroundExecutor:
    """单个守护线程、低优先级。进程退出时不等排队中的预热。"""

    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="v3-prewarm", daemon=True)
        self._thread.start()

    def submit(self, fn, *args):
        future = Future()
        self._queue.put((future, fn, args))
        return future

    def _run(self):
        _lower_priority()
        while True:
            future, fn, args = self._queue.get()
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(fn(*args))
            except BaseException as e:  # noqa: BLE001 交给主线程处理
                future.set_exception(e)


def _lower_priority():
    if sys.platform != "win32":
        return
    try:
        import ctypes
        kernel = ctypes.windll.kernel32
        kernel.SetThreadPriority(kernel.GetCurrentThread(), -1)  # BELOW_NORMAL
    except Exception:
        pass


def _locked(surface):
    """主线程与后台线程的合成互斥（rig 上有若干懒缓存）。"""
    if getattr(surface, "_v3_lock", None) is not None:
        return surface._v3_lock
    lock = threading.RLock()
    original = surface._compose_image

    def compose_image(*args, **kwargs):
        with lock:
            return original(*args, **kwargs)
    surface._compose_image = compose_image
    # 捏脸素材（每个表情第一次约 100～130ms）整段持锁：主线程看到的要么没有、要么完整。
    original_prepare = surface.cheek.prepare

    def prepare(*args, **kwargs):
        # 主线程每帧都会调一次。该表情的素材已经有了（或没有捏脸配置）时原函数什么都不做，
        # 这时不能去抢锁——后台正在合成眨眼帧时，抢锁会让这一帧白等最多 45ms。
        cheek = surface.cheek
        settings = args[1] if len(args) > 1 else kwargs.get("settings")
        if settings is not None and (not cheek.config or settings.expression in cheek.backgrounds):
            return None
        with lock:
            return original_prepare(*args, **kwargs)
    surface.cheek.prepare = prepare
    # 反应脸补丁（每张约 50ms，第一次捏脸/摸头/敲头/挠痒时才会建）同样整段持锁。
    original_patch = surface.reaction_face.patch

    def patch(*args, **kwargs):
        with lock:
            return original_patch(*args, **kwargs)
    surface.reaction_face.patch = patch
    surface._v3_lock = lock
    return lock


class Prewarmer:
    """每个渲染器一份。executor 可替换（测试用同步执行器）。"""

    _pool: _BackgroundExecutor | None = None

    def __init__(self, renderer, settings, executor=None):
        self.surface = renderer.head_surface
        _locked(self.surface)
        self.settings = settings
        self.executor = executor or self._shared_pool()
        self.pending: dict[tuple, object] = {}
        self.requested: set[tuple] = set()
        self.blink_requested: set[str] = set()
        self.closed = False

    @classmethod
    def _shared_pool(cls):
        if cls._pool is None:
            cls._pool = _BackgroundExecutor()
        return cls._pool

    def request(self, expression: str, levels=(1.0,)) -> None:
        settings = replace(self.settings, expression=expression)
        for level in levels:
            key = (expression, round(level, 5))
            if key in self.surface.frames or key in self.requested:
                continue
            self.requested.add(key)
            self.pending[key] = self.executor.submit(self._build, settings, level)

    def request_cheek(self, expression: str) -> None:
        """后台准备该表情的捏脸素材（否则第一次捏脸或第一次换到该表情时主线程卡一下）。"""
        key = (CHEEK_KEY, expression)
        if key in self.requested or not self.surface.cheek.config:
            return
        self.requested.add(key)
        self.pending[key] = self.executor.submit(self._prepare_cheek,
                                                 replace(self.settings, expression=expression))

    def request_reactions(self, expressions, faces) -> None:
        """后台建反应脸补丁：各状态表情的“擦除”补丁、各反应脸的睁眼补丁。"""
        key = (CHEEK_KEY, "reactions")
        if key in self.requested:
            return
        self.requested.add(key)
        self.pending[key] = self.executor.submit(self._prepare_reactions, tuple(expressions), tuple(faces))

    def _prepare_reactions(self, expressions, faces):
        reaction = self.surface.reaction_face
        for expression in expressions:
            if self.closed:
                return
            reaction.patch(expression, erase=True)
        for face in faces:
            if self.closed:
                return
            reaction.patch(face)

    def _prepare_cheek(self, settings):
        if not self.closed:
            self.surface.cheek.prepare(self.surface, settings)

    def request_blinks(self, expression: str) -> None:
        if expression in self.blink_requested:
            return
        self.blink_requested.add(expression)
        self.request(expression, BLINK_LEVELS)

    def cancel_blinks(self) -> None:
        """互动时不让后台继续合成眨眼帧（它们会占着锁，主线程渲染要等）。排队中的取消，
        正在跑的那一张（最多约 45ms）跑完；互动结束后 request_blinks 会补回来。"""
        for key, future in list(self.pending.items()):
            if key[0] != CHEEK_KEY and key[1] < 1.0 and future.cancel():
                del self.pending[key]
                self.requested.discard(key)
                self.blink_requested.discard(key[0])

    def _build(self, settings, level):
        if self.closed:
            return None
        return build_frame(self.surface, settings, level)

    def collect(self) -> int:
        """主线程调用：把已完成的帧放进缓存。返回放入数量。"""
        frames = self.surface.frames
        added = 0
        for key, future in list(self.pending.items()):
            if not future.done():
                continue
            del self.pending[key]
            try:
                frame = future.result()
            except Exception:  # 预热失败不影响显示：主线程会照常同步合成
                self.requested.discard(key)
                continue
            if key[0] == CHEEK_KEY:
                continue
            if frame is None or self.closed:
                continue
            if key not in frames:
                frames[key] = frame
                added += 1
            while len(frames) > 64:
                frames.popitem(last=False)
        return added

    def choose(self, expression: str, eye_scale: float) -> float:
        """要用的档还在预热时，先用已缓存的最近一档；都没有就原值（同步合成）。"""
        frames = self.surface.frames
        key = (expression, round(eye_scale, 5))
        if key in frames or key not in self.pending:
            return eye_scale
        ready = [k[1] for k in frames if k[0] == expression]
        if not ready:
            return eye_scale
        return min(ready, key=lambda level: abs(level - eye_scale))

    def close(self) -> None:
        self.closed = True
        for future in self.pending.values():
            future.cancel()
        self.pending.clear()
