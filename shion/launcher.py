"""拉起诗音 GUI 的公共代码：Claude 的 hook 用，app.py 用其中的 INSTANCE_NAME。

只用标准库、不 import Qt（hook 的启动时间很紧）。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTANCE_NAME = "ShionDesktopPet-single-instance"  # 单实例命名管道名，shion/app.py 也用它
ERROR_FILE_NOT_FOUND = 2
IS_WINDOWS = os.name == "nt"
_popen = subprocess.Popen  # 测试在 conftest 里统一替换掉，防止在开发机上真的拉起诗音


def _wait_named_pipe(path: str):
    """(管道是否存在且可连, GetLastError)。零网络开销：Windows 上连未监听的本机端口要等满超时，管道不用。"""
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.WaitNamedPipeW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
    kernel32.WaitNamedPipeW.restype = ctypes.c_int
    ok = bool(kernel32.WaitNamedPipeW(path, 1))
    return ok, 0 if ok else ctypes.get_last_error()


def shion_running():
    """诗音的单实例命名管道在不在：True = 在；False = 确定没开；None = 不确定（按原逻辑处理）。

    只有“管道不存在”（ERROR_FILE_NOT_FOUND）才算确定没开。设了 SHION_PORT 说明是测试/自定义环境，
    它的假服务器没有管道，不判断；任何异常、非 Windows、其他错误码都不判断。
    """
    try:
        if not IS_WINDOWS or os.environ.get("SHION_PORT"):
            return None
        ok, error = _wait_named_pipe("\\\\.\\pipe\\" + (os.environ.get("SHION_INSTANCE_NAME") or INSTANCE_NAME))
        if ok:
            return True
        return False if error == ERROR_FILE_NOT_FOUND else None
    except Exception:
        return None


def launch_shion(root: Path = ROOT) -> bool:
    """启动诗音 GUI，只 Popen、不等待它起来。返回是否已经发出启动。

    打包版用当前的 Shion.exe；源码版用 root/.venv 的 pythonw。exe 不存在就什么都不做。
    """
    frozen = getattr(sys, "frozen", False)
    exe = Path(sys.executable) if frozen else root / ".venv" / "Scripts" / "pythonw.exe"
    if not exe.exists():
        return False
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    for extra in (0x01000000, 0):  # CREATE_BREAKAWAY_FROM_JOB；被拒绝就去掉重试
        try:
            _popen(
                [str(exe)] + ([] if frozen else ["-m", "shion"]),
                cwd=str(exe.parent if frozen else root), creationflags=flags | extra,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env={**os.environ, "SHION_LAUNCHED_BY_HOOK": "1",
                     **({"PYINSTALLER_RESET_ENVIRONMENT": "1"} if frozen else {})},
            )
            return True
        except OSError:
            continue
    return False
