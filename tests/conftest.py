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
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / ".claude"))
    monkeypatch.setenv("SHION_DATA_DIR", str(home / "Shion"))
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))
    from shion.startup import Startup
    registry = FakeRegistry()
    monkeypatch.setattr(Startup, "registry", property(lambda self: self._registry or registry))
    return home


@pytest.fixture(autouse=True)
def fresh_hook_token():
    """hook 模块把令牌缓存在全局变量里；每个测试开始前清掉，免得带上一个测试的服务端令牌。"""
    import sys
    for module in list(sys.modules.values()):
        if getattr(module, "__file__", None) and str(module.__file__).endswith("shion_hook.py"):
            module._token = None
    yield


@pytest.fixture(autouse=True)
def register_server_tokens(monkeypatch):
    """测试里直接起的 ShionServer：启动后按端口登记令牌，并写进当前 SHION_DATA_DIR（见 tests/link_support.py）。"""
    from shion import server as server_mod
    from tests import link_support
    link_support.TOKENS.clear()
    original = server_mod.ShionServer.start

    def start(self):
        original(self)
        link_support.TOKENS[self.port] = self.token
        link_support.link(self)

    monkeypatch.setattr(server_mod.ShionServer, "start", start)
    yield
    link_support.TOKENS.clear()


@pytest.fixture(autouse=True)
def no_real_launch(monkeypatch):
    """任何测试都不能真的拉起诗音 GUI；要检查启动参数的测试自己再替换 _popen。"""
    from shion import launcher
    monkeypatch.setattr(launcher, "_popen", lambda *args, **kwargs: None)
