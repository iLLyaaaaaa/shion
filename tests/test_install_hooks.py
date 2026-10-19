import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"
spec = importlib.util.spec_from_file_location("hooks_config", TOOLS / "hooks_config.py")
hc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hc)

PREFIX = '"C:/p q/.venv/Scripts/python.exe" "C:/p q/hooks/shion_hook.py"'
USER = {
    "model": "opusplan",
    "hooks": {
        "Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}],
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "check.sh"}]}],
        "PostToolUse": [{"hooks": [{"type": "command", "command": "post.sh"}]}],
    },
}


def shion_cmds(settings):
    return [
        h["command"]
        for groups in settings.get("hooks", {}).values()
        for g in groups
        for h in g["hooks"]
        if hc.MARKER in h["command"]
    ]


def test_merge_into_empty():
    out = hc.merge({}, PREFIX)
    assert set(out["hooks"]) == set(hc.EVENTS)
    assert f"{PREFIX} SessionStart" in shion_cmds(out)
    assert out["hooks"]["PreToolUse"][0]["matcher"] == "*"
    assert out["hooks"]["SessionStart"][0]["hooks"][0]["timeout"] == 15


def test_merge_keeps_user_config_and_is_idempotent():
    original = copy.deepcopy(USER)
    once = hc.merge(USER, PREFIX)
    assert USER == original  # 不改入参
    assert once["model"] == "opusplan"
    assert once["hooks"]["PostToolUse"] == USER["hooks"]["PostToolUse"]
    assert once["hooks"]["Stop"][0] == USER["hooks"]["Stop"][0]
    assert once["hooks"]["PreToolUse"][0] == USER["hooks"]["PreToolUse"][0]
    twice = hc.merge(once, PREFIX)
    assert twice == once
    assert len(shion_cmds(twice)) == 5


def test_remove_restores_original():
    assert hc.remove(hc.merge(USER, PREFIX)) == USER
    assert hc.remove(hc.merge({}, PREFIX)) == {}
    assert hc.remove({"model": "x"}) == {"model": "x"}


def test_merge_rejects_bad_shapes():
    with pytest.raises(ValueError):
        hc.merge({"hooks": []}, PREFIX)
    with pytest.raises(ValueError):
        hc.merge({"hooks": {"Stop": {}}}, PREFIX)


def run_script(name, path):
    return subprocess.run(
        [sys.executable, str(TOOLS / name), "--settings", str(path)], capture_output=True, text=True
    )


def test_scripts_roundtrip_with_backup(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(USER), encoding="utf-8")
    assert run_script("install_hooks.py", p).returncode == 0
    installed = json.loads(p.read_text(encoding="utf-8"))
    assert len(shion_cmds(installed)) == 5
    backups = list(tmp_path.glob("settings.json.shion-backup-*"))
    assert len(backups) == 1 and json.loads(backups[0].read_text(encoding="utf-8")) == USER
    assert run_script("uninstall_hooks.py", p).returncode == 0
    assert json.loads(p.read_text(encoding="utf-8")) == USER


def test_install_creates_missing_file(tmp_path):
    p = tmp_path / "sub" / "settings.local.json"
    assert run_script("install_hooks.py", p).returncode == 0
    assert len(shion_cmds(json.loads(p.read_text(encoding="utf-8")))) == 5


def test_corrupt_json_not_touched(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("{坏", encoding="utf-8")
    for script in ("install_hooks.py", "uninstall_hooks.py"):
        r = run_script(script, p)
        assert r.returncode == 1 and "未被改写" in r.stderr
    assert p.read_text(encoding="utf-8") == "{坏"
    assert list(tmp_path.glob("*backup*")) == []


def test_default_command_starts_with_unquoted_word():
    # Claude Code 在 Windows 上可能用 PowerShell 跑 hook，以引号开头会解析失败
    cmd = hc.default_command_prefix(Path("C:/a b/proj"))
    assert cmd.startswith("python ")
    assert cmd.endswith('"C:/a b/proj/hooks/shion_hook.py"')


def test_uninstall_missing_or_unchanged_file_is_not_written(tmp_path):
    missing = tmp_path / "none.json"
    assert run_script("uninstall_hooks.py", missing).returncode == 0
    assert not missing.exists()
    p = tmp_path / "s.json"
    p.write_text('{"model":"x"}', encoding="utf-8")
    assert run_script("uninstall_hooks.py", p).returncode == 0
    assert p.read_text(encoding="utf-8") == '{"model":"x"}'
    assert list(tmp_path.glob("*backup*")) == []


def test_prefix_rejects_missing_python_and_bad_path(monkeypatch):
    monkeypatch.setattr(hc.shutil, "which", lambda name: None)
    with pytest.raises(ValueError):
        hc.default_command_prefix(Path("C:/proj"))
    monkeypatch.setattr(hc.shutil, "which", lambda name: "C:/Users/x/AppData/Local/Microsoft/WindowsApps/python.exe")
    with pytest.raises(ValueError):
        hc.default_command_prefix(Path("C:/proj"))
    monkeypatch.setattr(hc.shutil, "which", lambda name: "C:/Python/python.exe")
    with pytest.raises(ValueError):
        hc.default_command_prefix(Path("C:/pro$j"))


def test_bom_settings_are_readable(tmp_path):
    p = tmp_path / "s.json"
    p.write_bytes(b"\xef\xbb\xbf" + b'{"model":"x"}')
    assert hc.load(p) == {"model": "x"}
