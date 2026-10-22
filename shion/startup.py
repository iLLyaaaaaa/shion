"""当前用户的 Windows 自启项；不访问其他值，不启动任何程序。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Shion"
ROOT = Path(__file__).resolve().parent.parent


def launch_args(root: Path = ROOT) -> list[str]:
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).resolve())]
    return [str(root.resolve() / ".venv" / "Scripts" / "pythonw.exe"),
            str(root.resolve() / "shion" / "__main__.py")]


class Startup:
    def __init__(self, registry=None, root: Path = ROOT):
        self._registry = registry
        self.root = root

    @property
    def registry(self):
        if self._registry is None:
            import winreg
            self._registry = winreg
        return self._registry

    def command(self) -> str:
        return subprocess.list2cmdline(launch_args(self.root))

    def read(self) -> str | None:
        reg = self.registry
        try:
            with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_READ) as key:
                value, kind = reg.QueryValueEx(key, VALUE_NAME)
                if kind != reg.REG_SZ or not isinstance(value, str):
                    return ""  # 有值但不是本程序可运行的命令
                return value
        except FileNotFoundError:
            return None

    def inspect(self) -> str:
        """enabled / disabled / stale；读注册表失败由界面说明。"""
        value = self.read()
        if value is None:
            return "disabled"
        return "enabled" if value == self.command() and all(Path(p).is_file() for p in launch_args(self.root)) else "stale"

    def set_enabled(self, enabled: bool) -> None:
        reg = self.registry
        if enabled:
            if not all(Path(p).is_file() for p in launch_args(self.root)):
                raise ValueError("诗音的启动路径已失效")
            with reg.CreateKeyEx(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_SET_VALUE) as key:
                reg.SetValueEx(key, VALUE_NAME, 0, reg.REG_SZ, self.command())
        else:
            try:
                with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_SET_VALUE) as key:
                    reg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
