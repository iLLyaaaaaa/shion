"""连接服务只操作注入的临时用户/项目目录，不运行 Claude。"""
import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tools import hooks_config as hc


@pytest.fixture
def connection(tmp_path):
    root = tmp_path / "诗音 source with spaces"
    for name in (".venv/Scripts/python.exe", "hooks/shion_hook.py"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test")
    return hc.HookConnection(Path.home() / ".claude/settings.json",
                             root / ".claude/settings.local.json", root)


def put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def own(settings):
    return [h for groups in settings.get("hooks", {}).values()
            for g in groups for h in g["hooks"] if hc._is_shion(h)]


def test_connect_migrates_keeps_every_foreign_value_and_disconnects(connection):
    c = connection
    user = {"statusLine": {"type": "command", "command": "custom.exe"},
            "modelSettings": {"opus": {"thinking": True}}, "arbitrary": [1, {"a": "中"}],
            "hooks": {"Stop": [{"matcher": "mine", "other": "kept", "hooks": [
                {"type": "command", "command": "other.exe"}]}], "Unknown": []}}
    project = hc.merge({"permissions": {"allow": ["Read"]}}, *hc.runtime_command(c.root))
    # 同一个分组里混有第三方条目。
    project["hooks"]["Stop"][0]["hooks"].append({"type": "command", "command": "keep.exe"})
    put(c.user, user)
    put(c.project, project)
    original = {p: p.read_bytes() for p in (c.user, c.project)}
    result = c.connect("en")
    assert result.changed == (c.project, c.user)
    assert len(result.backups) == 2
    for backup in result.backups:
        target = c.user if backup.parent == c.user.parent else c.project
        assert backup.read_bytes() == original[target]
    installed = hc.load(c.user)
    assert hc.remove(installed) == user
    assert hc.load(c.project) == hc.remove(project)
    assert len(own(installed)) == len(hc.EVENTS)
    assert c.inspect().state == "connected"
    before = {p: p.read_bytes() for p in (c.user, c.project)}
    assert c.connect("en") == hc.WriteResult((), ())
    assert {p: p.read_bytes() for p in before} == before
    c.disconnect()
    assert hc.load(c.user) == user
    assert c.inspect().state == "disconnected"
    assert c.disconnect() == hc.WriteResult((), ())


@pytest.mark.parametrize("content", ["", "{bad", "[]", '{"hooks": []}',
                                      '{"hooks":{"Stop":[{}]}}'])
@pytest.mark.parametrize("location", ["user", "project"])
def test_bad_settings_are_never_written_or_migrated(connection, content, location):
    c = connection
    put(c.user, {"statusLine": "kept"})
    put(c.project, hc.merge({}, *hc.runtime_command(c.root)))
    getattr(c, location).write_text(content, encoding="utf-8")
    before = {p: p.read_bytes() for p in (c.user, c.project)}
    with pytest.raises(ValueError):
        c.connect()
    assert {p: p.read_bytes() for p in before} == before
    assert not list(c.root.parent.rglob("*.shion-backup-*"))
    if location == "user":
        assert c.inspect().state == "error"
        with pytest.raises(ValueError):
            c.disconnect()


def test_backup_failure_prevents_either_replacement(connection, monkeypatch):
    c = connection
    put(c.user, {"modelSettings": {"keep": 123}})
    put(c.project, hc.merge({}, *hc.runtime_command(c.root)))
    before = {p: p.read_bytes() for p in (c.user, c.project)}
    copy2 = hc.shutil.copy2
    def fail_user(src, dst):
        if src == c.user:
            raise PermissionError("backup denied")
        return copy2(src, dst)
    monkeypatch.setattr(hc.shutil, "copy2", fail_user)
    with pytest.raises(PermissionError):
        c.connect()
    assert {p: p.read_bytes() for p in before} == before
    assert not list(c.root.parent.rglob("*.tmp"))


def test_user_write_failure_restores_project_bytes(connection, monkeypatch):
    c = connection
    put(c.project, hc.merge({}, *hc.runtime_command(c.root)))
    original = c.project.read_bytes()
    replace = hc.os.replace
    calls = []
    def fail_user(src, dst):
        calls.append(dst)
        if dst == c.user:
            raise PermissionError("user write denied")
        return replace(src, dst)
    monkeypatch.setattr(hc.os, "replace", fail_user)
    with pytest.raises(PermissionError):
        c.connect()
    assert calls == [c.project, c.user, c.project]
    assert c.project.read_bytes() == original
    assert not c.user.exists()
    assert not list(c.root.parent.rglob("*.tmp"))


def test_failed_rollback_reports_backup_location(connection, monkeypatch):
    c = connection
    put(c.project, hc.merge({}, *hc.runtime_command(c.root)))
    replace = hc.os.replace
    count = [0]
    def fail_after_first(src, dst):
        count[0] += 1
        if count[0] > 1:
            raise PermissionError("denied")
        return replace(src, dst)
    monkeypatch.setattr(hc.os, "replace", fail_after_first)
    with pytest.raises(OSError, match="恢复失败.*shion-backup"):
        c.connect()


@pytest.mark.parametrize("command,args", [
    ("echo", ["C:/hooks/shion_hook.py", "Stop"]),
    ("python.exe", ["C:/hooks/not_shion_hook.py", "Stop"]),
    ("other.exe", ["--hook", "Stop"]),
    ("echo shion_hook.py Stop", []),
    ("python.exe", ["C:/hooks/shion_hook.py.notes", "Stop"]),
])
def test_similar_foreign_commands_are_preserved(command, args):
    settings = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": command, "args": args}]}]}}
    assert hc.remove(settings) == settings


def test_status_refreshes_for_partial_stale_and_external_edits(connection):
    c = connection
    assert c.inspect().state == "disconnected"
    c.connect()
    original = hc.load(c.user)
    partial = copy.deepcopy(original)
    del partial["hooks"]["Stop"]
    put(c.user, partial)
    assert c.inspect().state == "stale"
    c.connect()
    (c.root / "hooks/shion_hook.py").unlink()
    assert c.inspect().state == "stale"
    put(c.user, {"modelSettings": {}})
    assert c.inspect().state == "disconnected"


def test_frozen_commands_recognised_replaced_and_removed(connection, monkeypatch):
    c = connection
    exe = c.root / "Shion.exe"
    exe.write_bytes(b"exe")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    c.connect()
    assert all(h["command"] == exe.as_posix() and h["args"][0] == "--hook" for h in own(hc.load(c.user)))
    assert c.inspect().state == "connected"
    monkeypatch.delattr(sys, "frozen")
    assert c.inspect().state == "stale"
    c.connect()
    assert c.inspect().state == "connected"
    c.disconnect()
    assert hc.load(c.user) == {}


def test_default_cli_uses_fake_home_and_fake_project(connection):
    c = connection
    tools = c.root / "tools"
    tools.mkdir()
    for name in ("hooks_config.py", "install_hooks.py", "uninstall_hooks.py"):
        shutil.copy2(hc.ROOT / "tools" / name, tools / name)
    put(c.project, hc.merge({}, *hc.runtime_command(c.root)))
    for script in ("install_hooks.py", "uninstall_hooks.py"):
        result = subprocess.run([sys.executable, str(tools / script)], capture_output=True,
                                env=os.environ.copy(), timeout=15)
        assert result.returncode == 0, result.stderr
    assert hc.load(c.user) == {}
    assert hc.load(c.project) == {}


def test_concurrent_edit_is_not_overwritten(connection, monkeypatch):
    c = connection
    put(c.user, {"before": 1})
    stage = hc._stage
    def concurrent(path, content):
        tmp = stage(path, content)
        if path == c.user:
            put(c.user, {"external": "kept"})
        return tmp
    monkeypatch.setattr(hc, "_stage", concurrent)
    with pytest.raises(OSError, match="其他程序"):
        c.connect()
    assert hc.load(c.user) == {"external": "kept"}
