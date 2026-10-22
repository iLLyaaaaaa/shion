"""三语菜单、引导与状态；所有配置路径来自临时目录。"""
import json
import os
import subprocess
import sys

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from shion import state as S
from shion.panel import ConnectionPanel
from shion.speech import Priority
from tools.hooks_config import HookConnection, ROOT
from tests.test_controller import Env, env, find_action, qapp


@pytest.fixture
def connected_env(env, tmp_path):
    root = tmp_path / "source app"
    for name in (".venv/Scripts/python.exe", "hooks/shion_hook.py"):
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"test")
    env.ctl.connection = HookConnection(tmp_path / "home/.claude/settings.json",
                                        root / ".claude/settings.local.json", root)
    env.data.activity_level = "quiet"
    return env


@pytest.mark.parametrize("lang", ["zh", "en", "ja"])
def test_menu_confirm_connect_status_disconnect_in_each_language(connected_env, lang):
    e = connected_env
    ctl = e.ctl
    ctl.set_language(lang)
    ui = ctl.lines.ui
    menu = ctl.build_menu()
    find_action(menu, ui("menu_connect")).trigger()
    panel = ctl._connection_panel
    assert panel.isVisible()
    assert not ctl.connection.user.exists()  # 确认前不写
    assert "Claude Code" in panel._detail.text()
    assert "Claude" not in panel.windowTitle()
    panel._connect.click()
    assert ctl.connection.inspect().state == "connected"
    assert ui("connection_connected") in ctl.status_text()
    menu2 = ctl.build_menu()
    assert ui("menu_connect") not in [a.text() for a in menu2.actions()]
    find_action(menu2, ui("menu_disconnect")).trigger()
    assert ctl.connection.inspect().state == "disconnected"
    assert ui("connection_disconnected") in ctl.status_text()


def test_first_intro_finishes_before_prompt_and_later_is_flushed(connected_env):
    e = connected_env
    e.ctl.greet_startup(True)
    assert e.data.connection_prompt == "pending"
    assert S.load(e.path).connection_prompt == "pending"
    e.advance(0.1)
    assert e.ctl._connection_panel is None
    e.advance(30)
    panel = e.ctl._connection_panel
    assert panel.isVisible()
    assert panel._later.text() == "以后再说"
    panel._later.click()
    assert S.load(e.path).connection_prompt == "later"
    assert not e.ctl.connection.user.exists()
    e.advance(60)
    assert not panel.isVisible()


def test_old_save_skips_onboarding_and_new_pending_resumes(connected_env):
    e = connected_env
    e.ctl.greet_startup(False)
    assert S.load(e.path).connection_prompt == "skipped"
    e.advance(60)
    assert e.ctl._connection_panel is None
    e.data.connection_prompt = "pending"  # 上次退出前还没选
    e.ctl.greet_startup(False)
    e.advance(60)
    assert e.ctl._connection_panel.isVisible()


def test_failed_connection_still_records_choice_and_remains_retryable(connected_env):
    e = connected_env
    e.ctl.greet_startup(True)
    e.advance(60)
    path = e.ctl.connection.user
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")
    panel = e.ctl._connection_panel
    panel._connect.click()
    assert S.load(e.path).connection_prompt == "connect"
    assert path.read_text(encoding="utf-8") == "{broken"
    assert "失败" in e.said[-1]
    e.advance(60)
    assert not panel.isVisible()
    menu = e.ctl.build_menu()
    assert find_action(menu, "连接 Claude Code").isEnabled()
    assert "无法读取配置" in e.ctl.status_text()


def test_prompt_waits_for_high_priority_speech_and_permission_panel(connected_env):
    e = connected_env
    e.ctl.greet_startup(True)
    e.ctl.say("important", priority=Priority.HIGH)
    e.advance(1)
    assert e.ctl._connection_panel is None
    e.advance(20)
    panel = e.ctl._connection_panel
    assert panel.isVisible()
    # 模拟现有授权队列；连接面板隐藏，授权结束后恢复待选择。
    queue = e.ctl.hub.permissions
    request = queue.open("Bash", "echo hello", session="s1", key="key")
    e.ctl._sync_permission()
    assert not panel.isVisible()
    assert e.ctl._perm_panel.isVisible()
    queue.decide(request, False)
    e.advance(30)
    assert panel.isVisible()


def test_panel_language_move_and_cleanup(connected_env):
    e = connected_env
    e.ctl.open_connection()
    panel = e.ctl._connection_panel
    assert panel.windowFlags() & Qt.WindowDoesNotAcceptFocus
    assert panel.testAttribute(Qt.WA_ShowWithoutActivating)
    assert all(button.focusPolicy() == Qt.NoFocus for button in (panel._connect, panel._later))
    old = panel.pos()
    e.win.move(e.win.x() + 80, e.win.y() + 100)
    e.ctl._on_window_moved()
    assert panel.pos() != old
    e.ctl.set_language("en")
    assert panel._connect.text() == "Connect"
    QTest.keyClick(panel._connect, Qt.Key_Return)
    assert panel.isVisible() and not e.ctl.connection.user.exists()
    e.ctl.quit()
    assert not panel.isVisible()


def test_menu_startup_toggle_repair_and_error(connected_env, monkeypatch):
    e = connected_env
    menu = e.ctl.build_menu()
    action = find_action(menu, "开机自启")
    action.trigger()
    assert e.ctl.startup.inspect() == "enabled"
    menu2 = e.ctl.build_menu()
    action2 = find_action(menu2, "开机自启")
    assert action2.isChecked()
    action2.trigger()
    assert e.ctl.startup.inspect() == "disabled"
    e.ctl.startup.registry.values["Shion"] = ("old", 1)
    menu3 = e.ctl.build_menu()
    find_action(menu3, "开机自启（路径失效，点击修复）").trigger()
    assert e.ctl.startup.inspect() == "enabled"
    def denied(*args):
        raise PermissionError("denied")
    monkeypatch.setattr(e.ctl.startup.registry, "OpenKey", denied)
    menu4 = e.ctl.build_menu()
    assert not find_action(menu4, "开机自启").isEnabled()
    e.ctl.set_startup(False)
    assert "失败" in e.said[-1]


@pytest.mark.parametrize("choice", [None, "pending", "connect", "later", "skipped", "bad", []])
def test_prompt_save_field_is_optional_and_validated(choice):
    data = S.SaveData.from_dict({"connection_prompt": choice})
    assert data.connection_prompt == (choice if choice in ("pending", "connect", "later", "skipped") else None)
    assert S.SaveData.from_dict(data.to_dict()).connection_prompt == data.connection_prompt


def test_hook_entry_is_standard_library_only_and_direct_entry_works(tmp_path):
    code = """
import builtins
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.startswith('PySide6'):
        raise AssertionError('hook mode loaded GUI')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from shion.__main__ import main
raise SystemExit(main(['--hook', 'Stop']))
"""
    child_env = {**os.environ, "SHION_PORT": "1"}
    result = subprocess.run([sys.executable, "-c", code], input=b"{}", capture_output=True,
                            env=child_env, timeout=10)
    assert result.returncode == 0, result.stderr
    direct = subprocess.run([sys.executable, str(ROOT / "shion/__main__.py"), "--help"],
                            cwd=tmp_path, env=child_env, capture_output=True, timeout=15)
    assert direct.returncode == 0, direct.stderr
    assert b"--snapshot" in direct.stdout


def test_frozen_hook_launch_uses_current_exe_without_python(tmp_path, monkeypatch):
    from hooks import shion_hook as hook
    exe = tmp_path / "Shion.exe"
    exe.write_bytes(b"test")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    calls = []
    monkeypatch.setattr(hook.subprocess, "Popen", lambda args, **kw: calls.append((args, kw)))
    hook.launch_shion()
    assert calls[0][0] == [str(exe)]
    assert calls[0][1]["cwd"] == str(tmp_path)
    assert calls[0][1]["env"]["SHION_LAUNCHED_BY_HOOK"] == "1"


def test_source_startup_command_runs_from_unrelated_workdir(tmp_path):
    from shion.startup import launch_args
    from tests.test_app_server import free_port, http, log_text, wait_for
    port = free_port()
    data = tmp_path / "startup-data"
    child_env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "SHION_DATA_DIR": str(data),
                 "SHION_PORT": str(port), "SHION_INSTANCE_NAME": f"ShionStartupTest-{os.getpid()}"}
    proc = subprocess.Popen(launch_args(), cwd=tmp_path, env=child_env,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert wait_for(lambda: http(port, "GET", "/health") == {"ok": True}), log_text(data / "shion.log")
        assert proc.poll() is None
    finally:
        proc.kill()
        proc.wait(timeout=10)
