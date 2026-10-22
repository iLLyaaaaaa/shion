"""所有测试（包括子进程）的用户配置隔离；禁止碰真实 Claude 设置和自启项。"""
import os

import pytest


class FakeRegistry:
    HKEY_CURRENT_USER = "HKCU"
    KEY_READ, KEY_SET_VALUE, REG_SZ = 1, 2, 1

    def __init__(self):
        self.values = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def OpenKey(self, hive, path, reserved=0, access=0):
        assert hive == self.HKEY_CURRENT_USER
        return self

    CreateKeyEx = OpenKey

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name]

    def SetValueEx(self, key, name, reserved, kind, value):
        self.values[name] = (value, kind)

    def DeleteValue(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


@pytest.fixture(autouse=True)
def isolated_user(tmp_path_factory, monkeypatch):
    # 与业务 tmp_path 分开：素材工具的测试会严格检查输出目录内容。
    home = tmp_path_factory.mktemp("isolated-home")
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(home))
    drive, tail = os.path.splitdrive(str(home))
    monkeypatch.setenv("HOMEDRIVE", drive)
    monkeypatch.setenv("HOMEPATH", tail)
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    monkeypatch.setenv("SHION_DATA_DIR", str(home / "Shion"))
    from shion.startup import Startup
    registry = FakeRegistry()
    monkeypatch.setattr(Startup, "registry", property(lambda self: self._registry or registry))
    return home
