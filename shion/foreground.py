"""Claude 在前台时，让普通层级的诗音窗口组紧邻其上；不激活、不绑定 owner。"""
from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes
from pathlib import PureWindowsPath

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from shion.winproc import process_image

log = logging.getLogger("shion.foreground")

EVENT_SYSTEM_FOREGROUND = 0x0003
WINEVENT_OUTOFCONTEXT = 0x0000
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_NOOWNERZORDER = 0x0200
POSITION_FLAGS = SWP_NOACTIVATE | SWP_NOMOVE | SWP_NOSIZE | SWP_NOOWNERZORDER
GW_HWNDPREV = 3
GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008


def _native_windows() -> bool:
    return sys.platform == "win32" and QGuiApplication.platformName() == "windows"


class _Win32ForegroundApi:
    """窄 Win32 接口；测试可整体替换，不需要真实前台或进程。"""

    def __init__(self):
        self.callback_type = ctypes.WINFUNCTYPE(
            None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
            wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD,
        )
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        signatures = {
            "SetWinEventHook": ([wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE,
                                 self.callback_type, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.DWORD], wintypes.HANDLE),
            "UnhookWinEvent": ([wintypes.HANDLE], wintypes.BOOL),
            "GetForegroundWindow": ([], wintypes.HWND),
            "GetWindowThreadProcessId": ([wintypes.HWND, ctypes.POINTER(wintypes.DWORD)],
                                         wintypes.DWORD),
            "IsWindow": ([wintypes.HWND], wintypes.BOOL),
            "IsWindowVisible": ([wintypes.HWND], wintypes.BOOL),
            "IsIconic": ([wintypes.HWND], wintypes.BOOL),
            "GetWindow": ([wintypes.HWND, wintypes.UINT], wintypes.HWND),
            "GetWindowLongW": ([wintypes.HWND, ctypes.c_int], wintypes.LONG),
            "SetWindowPos": ([wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, wintypes.UINT], wintypes.BOOL),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.user32, name)
            fn.argtypes, fn.restype = args, result

    def callback(self, fn):
        return self.callback_type(fn)

    def register(self, callback):
        return self.user32.SetWinEventHook(
            EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND, None, callback,
            0, 0, WINEVENT_OUTOFCONTEXT,
        )

    def unregister(self, hook):
        return self.user32.UnhookWinEvent(hook)

    def foreground(self):
        return self.user32.GetForegroundWindow()

    def usable(self, hwnd):
        return (self.user32.IsWindow(hwnd) and self.user32.IsWindowVisible(hwnd)
                and not self.user32.IsIconic(hwnd))

    def pid(self, hwnd):
        pid = wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value

    def image(self, pid):
        return process_image(pid)

    def previous(self, hwnd):
        return self.user32.GetWindow(hwnd, GW_HWNDPREV)

    def topmost(self, hwnd):
        return bool(self.user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST)

    def position(self, hwnd, after):
        return self.user32.SetWindowPos(hwnd, after, 0, 0, 0, 0, POSITION_FLAGS)


class ForegroundFollower(QObject):
    """windows() 按从后到前返回当前窗口；每次处理现取，支持延迟创建及 HWND 重建。"""

    def __init__(self, windows, parent=None, *, api_factory=None):
        super().__init__(parent)
        self._windows = windows
        self._api_factory = api_factory or _Win32ForegroundApi
        self._api = None
        self._hook = None
        self._callback = None  # Unhook 成功前必须保留，不能让 ctypes 回调被回收
        self._enabled = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._sync)
        self._app = QApplication.instance()
        if self._app is not None:
            self._app.aboutToQuit.connect(self.stop)

    def set_enabled(self, enabled: bool) -> None:
        if not enabled:
            self.stop()
            return
        if self._enabled or not _native_windows():
            return
        try:
            if not self._hook:
                self._api = self._api_factory()
                self._callback = self._api.callback(self._on_event)
                self._hook = self._api.register(self._callback)
            if not self._hook:
                self._callback = None
                log.warning("无法注册前台窗口 hook，跳过 Claude 层级跟随")
                return
        except Exception:
            self._callback = None
            log.exception("注册前台窗口 hook 失败，跳过 Claude 层级跟随")
            return
        self._enabled = True
        if self._app is not None:
            self._app.installEventFilter(self)
        self._request_sync()  # 启动/关闭置顶时，Claude 可能已经在前台

    def stop(self) -> None:
        self._enabled = False
        self._timer.stop()
        if self._app is not None:
            self._app.removeEventFilter(self)
        if self._hook:
            try:
                if not self._api.unregister(self._hook):
                    log.warning("注销前台窗口 hook 失败，保留回调并在下次清理时重试")
                    return
            except Exception:
                log.exception("注销前台窗口 hook 失败，保留回调")
                return
        self._hook = self._callback = None

    def _request_sync(self) -> None:
        if self._enabled and not self._timer.isActive():
            self._timer.start()

    def _on_event(self, hook, event, hwnd, object_id, child_id, thread, time) -> None:
        # WinEvent 回调只投递合并请求：不查进程、不做 Z 序操作，也不运行事件循环。
        if event == EVENT_SYSTEM_FOREGROUND and hwnd:
            self._request_sync()

    def eventFilter(self, watched, event):
        if self._enabled and event.type() in (QEvent.Show, QEvent.WinIdChange):
            if any(watched is window for window in self._windows()):
                self._request_sync()
        return False

    def _sync(self) -> None:
        if not self._enabled:
            return
        try:
            api = self._api
            target = api.foreground()
            if not target or not api.usable(target):
                return
            pid = api.pid(target)
            if not pid or PureWindowsPath(api.image(pid)).name.casefold() != "claude.exe":
                return
            # 进程查询后重验，避免把过期 Claude 事件应用到别的前台程序。
            if api.foreground() != target or not api.usable(target) or api.pid(target) != pid:
                return
            handles = []
            for window in self._windows():
                if window is not None and window.isVisible():
                    hwnd = int(window.winId())
                    if hwnd not in handles and api.usable(hwnd):
                        handles.append(hwnd)
            if not handles:
                return
            anchor = api.previous(target)
            seen = {target}
            while anchor in handles:
                if anchor in seen:  # Z 序在查询期间变化，等下一次事件，避免循环
                    return
                seen.add(anchor)
                anchor = api.previous(anchor)
            # 插到 topmost 窗口之后会意外继承置顶；HWND_TOP 保持普通层级。
            if not anchor or api.topmost(anchor):
                anchor = 0
            # SetWindowPos 的 after 在目标上方；先放最前的附属窗口，最后放本体。
            for hwnd in reversed(handles):
                if api.foreground() != target or not api.usable(target):
                    return
                if not api.position(hwnd, anchor):
                    log.warning("调整 Claude 上方窗口层级失败，停止本次跟随")
                    return
                anchor = hwnd
        except Exception:
            log.exception("Claude 窗口层级跟随失败，跳过本次事件")
