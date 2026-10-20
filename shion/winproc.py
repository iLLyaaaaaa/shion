"""Windows 进程表的小工具（只用标准库 ctypes，不 import Qt）。hook 脚本也会用它。

非 Windows 上各函数返回空结果，调用方按“找不到进程”处理。
"""
from __future__ import annotations

import os
from typing import Optional

EPOCH_DIFF = 116444736000000000  # 1601-01-01 到 1970-01-01 的 100 纳秒数


def filetime_to_unix(value: int) -> float:
    return (value - EPOCH_DIFF) / 1e7


def _k32():
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.OpenProcess.restype = wintypes.HANDLE
    return k32


def process_table() -> dict[int, tuple[int, str]]:
    """{pid: (父 pid, 可执行文件名)}；用 Toolhelp 快照。失败返回空 dict。"""
    if os.name != "nt":
        return {}
    import ctypes
    from ctypes import wintypes

    class ENTRY(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]

    k32 = _k32()
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not snap or snap == wintypes.HANDLE(-1).value:
        return {}
    table = {}
    try:
        entry = ENTRY()
        entry.dwSize = ctypes.sizeof(ENTRY)
        ok = k32.Process32FirstW(wintypes.HANDLE(snap), ctypes.byref(entry))
        while ok:
            table[entry.th32ProcessID] = (entry.th32ParentProcessID, entry.szExeFile)
            ok = k32.Process32NextW(wintypes.HANDLE(snap), ctypes.byref(entry))
    finally:
        k32.CloseHandle(wintypes.HANDLE(snap))
    return table


def process_created(pid: int) -> Optional[int]:
    """进程创建时间（FILETIME，100 纳秒），用来防 PID 复用；拿不到返回 None。"""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes
    k32 = _k32()
    handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not k32.GetProcessTimes(wintypes.HANDLE(handle), *[ctypes.byref(t) for t in times]):
            return None
        return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    finally:
        k32.CloseHandle(wintypes.HANDLE(handle))


def process_image(pid: int) -> str:
    """可执行文件的完整路径；拿不到返回空串。"""
    if os.name != "nt":
        return ""
    import ctypes
    from ctypes import wintypes
    k32 = _k32()
    handle = k32.OpenProcess(0x1000, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if not k32.QueryFullProcessImageNameW(wintypes.HANDLE(handle), 0, buf, ctypes.byref(size)):
            return ""
        return buf.value
    finally:
        k32.CloseHandle(wintypes.HANDLE(handle))


def terminate(pid: int, created: Optional[int] = None) -> bool:
    """结束一个进程；给了 created 时先核对创建时间（防 PID 复用）。"""
    if os.name != "nt":
        return False
    if created is not None and process_created(pid) != created:
        return False
    from ctypes import wintypes
    k32 = _k32()
    handle = k32.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
    if not handle:
        return False
    try:
        return bool(k32.TerminateProcess(wintypes.HANDLE(handle), 1))
    finally:
        k32.CloseHandle(wintypes.HANDLE(handle))
