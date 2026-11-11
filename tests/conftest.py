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
    monkeypatch.setenv("LOCALAPPDATA", str(home / "AppData" / "Local"))
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


@pytest.fixture(autouse=True, scope="session")
def stop_v3_prewarm_thread():
    """整个测试会话结束时关掉 V3 后台预热线程，不让它在解释器收尾时还在 PIL/numpy 里跑。"""
    yield
    import sys
    module = sys.modules.get("shion.v3_prewarm")
    if module is not None:
        module.Prewarmer.shutdown_pool()


@pytest.fixture(autouse=True, scope="session")
def destroy_leftover_windows():
    """整轮测试结束时销毁还活着的 Qt 窗口和定时器。

    显示过的顶层窗口如果活到解释器退出（例如信号连着捕获 self 的 lambda，gc 回收不了），
    PySide6 退出时的析构顺序不定，进程会在打印汇总后偶发崩溃（0xC0000409 / abort / access violation）。
    各测试仍应自己清理；这里只是兜底，保证整轮的退出码可信。
    """
    yield
    import gc
    import sys
    if "PySide6.QtWidgets" not in sys.modules:
        return
    from PySide6.QtCore import QCoreApplication, QEvent, QTimer
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        return
    for obj in gc.get_objects():
        try:
            if isinstance(obj, QTimer):
                obj.stop()
        except RuntimeError:  # C++ 对象已删除
            pass
    for widget in app.topLevelWidgets():
        widget.hide()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
