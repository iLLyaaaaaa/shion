"""冻结程序与源码共用的启动细节；只用标准库，不加载 Qt。"""
from __future__ import annotations

import io
import os
from pathlib import Path
import sys


def _windows_stream(number: int, reading: bool):
    """接回 windowed exe 继承的管道/重定向文件，拥有副本而非父进程的句柄。"""
    import ctypes
    from ctypes import wintypes
    import msvcrt

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel.GetStdHandle.restype = wintypes.HANDLE
    kernel.GetFileType.argtypes = [wintypes.HANDLE]
    kernel.GetFileType.restype = wintypes.DWORD
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.DuplicateHandle.argtypes = [
        wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
        ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD, wintypes.BOOL, wintypes.DWORD,
    ]
    kernel.DuplicateHandle.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.GetStdHandle(number)
    # 不附着/创建控制台；只接回调用者明确提供的文件和管道。
    if not handle or handle == wintypes.HANDLE(-1).value or kernel.GetFileType(handle) not in (1, 3):
        raise OSError("没有继承的标准流")
    duplicate = wintypes.HANDLE()
    process = kernel.GetCurrentProcess()
    if not kernel.DuplicateHandle(process, handle, process, ctypes.byref(duplicate), 0, False, 2):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        fd = msvcrt.open_osfhandle(duplicate.value, (os.O_RDONLY if reading else os.O_WRONLY) | os.O_BINARY)
    except BaseException:
        kernel.CloseHandle(duplicate)
        raise
    raw = os.fdopen(fd, "rb" if reading else "wb", buffering=0)
    return io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="\n", write_through=True)


def prepare_standard_streams() -> None:
    """PyInstaller noconsole 可能把标准流设为 None，hook 仍需 UTF-8 stdin/stdout。"""
    for name, number in (("stdin", -10), ("stdout", -11), ("stderr", -12)):
        if getattr(sys, name) is not None:
            # 部分 bootloader/父进程组合保留标准流，但文本编码仍是系统 GBK。
            reconfigure = getattr(getattr(sys, name), "reconfigure", None)
            if getattr(sys, "frozen", False) and reconfigure is not None:
                reconfigure(encoding="utf-8", errors="replace")
            continue
        reading = name == "stdin"
        try:
            stream = _windows_stream(number, reading) if os.name == "nt" else None
        except OSError:
            stream = None
        if stream is None:
            stream = open(os.devnull, "r" if reading else "w", encoding="utf-8")
        setattr(sys, name, stream)


def console_send_command(pid: int, created: int, text: str) -> list[str]:
    prefix = ["--console-send"] if getattr(sys, "frozen", False) else ["-m", "shion.console_send"]
    return [sys.executable, *prefix, "--pid", str(pid), "--created", str(created), "--text", text]


def hook_process_images(root: Path) -> tuple[str, ...]:
    exe = Path(sys.executable) if getattr(sys, "frozen", False) else root / ".venv" / "Scripts" / "python.exe"
    return (str(exe),)
