"""V3 头部帧的眨眼量化与后台预热。

头部整张合成（所有头发层 + 脸 + LANCZOS 缩放）一次约 45ms。眼睛开合度若是
连续值，每次眨眼的每一帧都命中不了缓存。这里：
- 把开合度量化到 0.05 一档（0.1～1 共 19 档）；
- 在一个后台线程里提前合成各表情的睁眼帧、当前表情的全部眨眼档；
- 结果只在主线程放进 HeadSurface.frames（缓存本身不跨线程写）。
"""
from __future__ import annotations

import atexit
import queue
import sys
import threading
from concurrent.futures import Future
from dataclasses import replace

EYE_STEP = 0.05
CHEEK_KEY = "cheek-prepare"  # pending/requested 里捏脸素材任务的键前缀
EYE_MIN = 0.1
FRAME_LIMIT = 64  # 与 HeadSurface.compose 的上限相同


class InlineExecutor:
    """在当前线程里立刻执行的“线程池”：截图和配图要确定性，不能等后台预热的快慢决定哪一帧用上预热好的图。"""

    def submit(self, fn, *args):
        future = Future()
        try:
            future.set_result(fn(*args))
        except Exception as error:  # 和线程池一样把异常交给 future；KeyboardInterrupt / SystemExit 照常向上抛
            future.set_exception(error)
        return future


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


_STOP = object()  # 队列哨兵：线程见到就退出


class _BackgroundExecutor:
    """单个守护线程、低优先级。退出时 shutdown()：取消排队任务，等正在跑的那一个做完（S7）。"""

    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        self._stopping = False
        self._thread = threading.Thread(target=self._run, name="v3-prewarm", daemon=True)
        self._thread.start()

    def submit(self, fn, *args):
        future = Future()
        if self._stopping:
            future.cancel()
            return future
        self._queue.put((future, fn, args))
        return future

    def shutdown(self, timeout: float = 1.0) -> bool:
        """返回线程是否已经结束。"""
        self._stopping = True
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is not _STOP:
                item[0].cancel()
        self._queue.put(_STOP)
        if self._thread is not threading.current_thread():
            self._thread.join(timeout)
        return not self._thread.is_alive()

    def _run(self):
        _lower_priority()
        while True:
            item = self._queue.get()
            if item is _STOP or self._stopping:
                if item is not _STOP:
                    item[0].cancel()
                return
            future, fn, args = item
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
        # 判断用“整段做完”的集合，不能看 cheek.backgrounds：后台做到一半时它已经有了，
        # 但 protection 等还没写，主线程跳过锁直接用会 KeyError。
        cheek = surface.cheek
        settings = args[1] if len(args) > 1 else kwargs.get("settings")
        if settings is not None and (not cheek.config or settings.expression in done):
            return None
        with lock:
            result = original_prepare(*args, **kwargs)
            if settings is not None:
                done.add(settings.expression)
            return result
    done: set = set()
    surface._v3_cheek_done = done
    surface.cheek.prepare = prepare
    # 反应脸补丁（每张约 50ms，第一次捏脸/摸头/敲头/挠痒时才会建）同样整段持锁。
    original_patch = surface.reaction_face.patch
    reaction = surface.reaction_face

    def patch(face, eye_scale=1., erase=False):
        # 补丁已缓存就直接用，不抢锁：反应进行中每帧都会调，后台合成眨眼帧时抢锁要白等 ~45ms。
        key = (face, round(eye_scale, 5), erase)
        hit = reaction.cache.get(key)
        if hit is not None:
            try:
                reaction.cache.move_to_end(key)  # 保持 LRU；后台恰好把它挤掉也没关系
            except KeyError:
                pass
            return hit
        with lock:
            return original_patch(face, eye_scale, erase)
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
        # 只记捏脸素材、反应脸这类“做一次就一直在”的任务；头部帧按“在缓存里或在排队”判重，
        # 被缓存淘汰后可以再请求（S7 审查第 2 条）。
        self.requested: set[tuple] = set()
        self.failed: set[tuple] = set()
        self.closed = False

    _atexit = False

    @classmethod
    def _shared_pool(cls):
        if cls._pool is None:
            cls._pool = _BackgroundExecutor()
            if not Prewarmer._atexit:
                atexit.register(Prewarmer.shutdown_pool)
                Prewarmer._atexit = True
        return cls._pool

    @classmethod
    def shutdown_pool(cls, timeout: float = 1.0) -> bool:
        """关掉共享后台线程（进程退出、测试结束时）；之后再用会重建。"""
        pool, Prewarmer._pool = Prewarmer._pool, None
        return True if pool is None else pool.shutdown(timeout)

    def request(self, expression: str, levels=(1.0,)) -> None:
        settings = replace(self.settings, expression=expression)
        frames = self.surface.frames
        for level in levels:
            key = (expression, round(level, 5))
            if key in frames or key in self.pending or key in self.failed:
                continue
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
        """每帧调用：只补当前表情缺的眨眼档（被淘汰的也会补回来）。"""
        frames, pending = self.surface.frames, self.pending
        missing = [level for level in BLINK_LEVELS
                   if (expression, level) not in frames and (expression, level) not in pending]
        if missing:
            self.request(expression, missing)

    def would_block(self, settings, pose) -> bool:
        """这一帧要现算的东西（头部帧、捏脸素材、反应脸补丁）有没缓存的，且锁正被后台占着。"""
        surface = self.surface
        reaction_face = pose.reaction_face
        eye = 1.0 if reaction_face is not None else round(pose.eye_scale, 5)
        expression = settings.expression
        need = (expression, eye) not in surface.frames
        cheek = surface.cheek
        if not need and settings.pinch and cheek.config:
            need = expression not in surface._v3_cheek_done
        if not need and reaction_face is not None:
            cache = surface.reaction_face.cache
            need = ((expression, 1.0, True) not in cache
                    or (reaction_face, round(pose.eye_scale, 5), False) not in cache)
        if not need:
            return False
        lock = surface._v3_lock
        if lock.acquire(blocking=False):
            lock.release()
            return False
        return True

    def side_ready(self, expression: str) -> bool:
        """换边用：该表情的睁眼帧、闭眼档、捏脸素材都已就绪（主线程换过去不会现算）。"""
        frames = self.surface.frames
        cheek = self.surface.cheek
        return ((expression, 1.0) in frames and (expression, BLINK_LEVELS[0]) in frames
                and (not cheek.config or expression in self.surface._v3_cheek_done))

    def cancel_blinks(self) -> None:
        """互动时不让后台继续合成眨眼帧（它们会占着锁，主线程渲染要等）。排队中的取消，
        正在跑的那一张（最多约 45ms）跑完；互动结束后 request_blinks 会补回来。"""
        for key, future in list(self.pending.items()):
            if key[0] != CHEEK_KEY and key[1] < 1.0 and future.cancel():
                del self.pending[key]

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
            if future.cancelled():
                continue
            try:
                frame = future.result()
            except Exception:  # 预热失败不影响显示：主线程会照常同步合成；这一项不再重试
                self.failed.add(key)
                continue
            if key[0] == CHEEK_KEY:
                continue
            if frame is None or self.closed:
                continue
            if key not in frames:
                frames[key] = frame
                added += 1
            self._evict(frames)
        return added

    def _evict(self, frames) -> None:
        """超过上限时从最旧的开始淘汰，但先不动当前表情的帧（它的睁眼帧可能很久没被访问）。"""
        if len(frames) <= FRAME_LIMIT:
            return
        current = self.settings.expression
        for key in [k for k in frames if k[0] != current]:
            if len(frames) <= FRAME_LIMIT:
                return
            del frames[key]
        while len(frames) > FRAME_LIMIT:
            frames.popitem(last=False)

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

    def close(self) -> list:
        """取消排队任务；返回取消不掉、还在跑的 future（窗口等它们结束后再做一次 GC）。"""
        self.closed = True
        running = []
        for future in self.pending.values():
            if not future.cancel() and not future.done():
                running.append(future)
        self.pending.clear()
        return running
