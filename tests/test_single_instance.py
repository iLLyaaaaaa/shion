"""单实例：Windows 命名互斥锁（原子）+ 套接字服务器（管道仍供 hook / 观察端判断诗音是否在运行）。"""
import os
import time

import pytest
from PySide6.QtNetwork import QLocalServer

from shion import app
from shion.app import SingleInstance
from tests.test_controller import qapp  # noqa: F401  QApplication fixture

windows_only = pytest.mark.skipif(os.name != "nt", reason="命名互斥锁只在 Windows 上使用")


def unique():
    return f"ShionMutexTest-{os.getpid()}-{time.monotonic_ns()}"


@windows_only
def test_mutex_makes_second_acquire_fail_even_before_the_pipe_exists(qapp):
    name = unique()
    a, b = SingleInstance(name), SingleInstance(name)
    try:
        assert a.acquire() is True
        a._server.close()  # 赢家还没来得及（或没法）提供管道：锁仍然拦住后来者
        assert b.acquire() is False
        assert b._server is None and b._mutex == 0
    finally:
        a.release()
        b.release()


@windows_only
def test_release_frees_the_mutex_and_pipe_for_the_next_instance(qapp):
    name = unique()
    a = SingleInstance(name)
    assert a.acquire() is True and a._mutex
    a.release()
    assert a._mutex == 0 and a._server is None
    b = SingleInstance(name)
    try:
        assert b.acquire() is True
    finally:
        b.release()


@windows_only
def test_existing_mutex_means_no_listen(qapp, monkeypatch):
    name = unique()
    closed = []
    monkeypatch.setattr(app, "_create_mutex", lambda n: (11, True))
    monkeypatch.setattr(app, "_close_handle", closed.append)
    monkeypatch.setattr(QLocalServer, "listen", lambda self, n: (_ for _ in ()).throw(AssertionError("不该 listen")))
    inst = SingleInstance(name)
    assert inst.acquire() is False
    assert closed == [11] and inst._mutex == 0  # 本次拿到的句柄只是已有锁的另一个引用，立刻关掉


@windows_only
def test_mutex_name_is_local_prefixed_and_follows_the_instance_name(qapp, monkeypatch):
    seen = []
    monkeypatch.setattr(app, "_create_mutex", lambda n: seen.append(n) or (0, False))
    name = unique()
    inst = SingleInstance(name)
    try:
        assert inst.acquire() is True  # 句柄为 0：退回纯管道逻辑
    finally:
        inst.release()
    assert seen == [name]


@windows_only
def test_real_mutex_uses_local_namespace_and_instance_name(qapp):
    import ctypes
    from ctypes import wintypes
    name = unique()
    inst = SingleInstance(name)
    try:
        assert inst.acquire() is True
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.OpenMutexW.restype = wintypes.HANDLE
        handle = kernel32.OpenMutexW(0x00100000, False, "Local\\" + name)  # SYNCHRONIZE
        assert handle
        app._close_handle(handle)
    finally:
        inst.release()


@windows_only
def test_mutex_failure_falls_back_to_the_pipe_logic(qapp, monkeypatch):
    name = unique()
    monkeypatch.setattr(app, "_create_mutex", lambda n: (_ for _ in ()).throw(OSError("no kernel32")))
    a, b = SingleInstance(name), SingleInstance(name)
    try:
        assert a.acquire() is True
        assert b.acquire() is False  # 仍靠管道判断
    finally:
        a.release()
        b.release()


@windows_only
def test_listen_failure_releases_the_mutex(qapp, monkeypatch):
    closed = []
    monkeypatch.setattr(app, "_create_mutex", lambda n: (22, False))
    monkeypatch.setattr(app, "_close_handle", closed.append)
    monkeypatch.setattr(QLocalServer, "listen", lambda self, n: False)
    inst = SingleInstance(unique())
    assert inst.acquire() is False
    assert closed == [22] and inst._mutex == 0 and inst._server is None


@windows_only
def test_old_instance_without_mutex_is_still_detected_by_its_pipe(qapp, monkeypatch):
    name = unique()
    old = QLocalServer()  # 旧版诗音：只有管道，没有互斥锁
    assert old.listen(name)
    closed = []
    real_close = app._close_handle
    monkeypatch.setattr(app, "_close_handle", lambda h: closed.append(h) or real_close(h))
    inst = SingleInstance(name)
    try:
        assert inst.acquire() is False
        assert len(closed) == 1 and inst._mutex == 0  # 拿到的锁已释放，不挡住后来的新实例
    finally:
        inst.release()
        old.close()
    fresh = SingleInstance(name)
    try:
        assert fresh.acquire() is True
    finally:
        fresh.release()


def test_non_windows_never_touches_the_mutex(qapp, monkeypatch):
    monkeypatch.setattr(app.sys, "platform", "linux")
    monkeypatch.setattr(app, "_create_mutex", lambda n: (_ for _ in ()).throw(AssertionError("不该创建互斥锁")))
    monkeypatch.setattr(app, "_close_handle", lambda h: (_ for _ in ()).throw(AssertionError("不该关闭句柄")))
    name = unique()
    a, b = SingleInstance(name), SingleInstance(name)
    try:
        assert a.acquire() is True
        assert b.acquire() is False
    finally:
        a.release()
        b.release()
    assert a._mutex == 0 and b._mutex == 0  # 纯管道逻辑，和原来一致
