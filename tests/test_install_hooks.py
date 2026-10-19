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

PY = "C:/p q/.venv/Scripts/python.exe"
SCRIPT = "C:/p q/hooks/shion_hook.py"
USER = {
    "model": "opusplan",
    "hooks": {
        "Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}],
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "check.sh"}]}],
        "PostToolUse": [{"hooks": [{"type": "command", "command": "post.sh"}]}],
    },
}


def shion_cmds(settings):
    """返回 (命令, 参数) 列表。"""
    return [
        (h["command"], tuple(h.get("args", ())))
        for groups in settings.get("hooks", {}).values()
        for g in groups
        for h in g["hooks"]
        if hc._is_shion(h)
    ]


def test_merge_into_empty():
    out = hc.merge({}, PY, SCRIPT)
    assert set(out["hooks"]) == set(hc.EVENTS)
    assert (PY, (SCRIPT, "SessionStart")) in shion_cmds(out)
    assert (PY, (SCRIPT, "PostToolUseFailure")) in shion_cmds(out)
    assert all("command" in h and "args" in h for g in out["hooks"].values() for x in g for h in x["hooks"])
    assert out["hooks"]["PreToolUse"][0]["matcher"] == "*"
    assert out["hooks"]["SessionStart"][0]["hooks"][0]["timeout"] == 15


def test_merge_keeps_user_config_and_is_idempotent():
    original = copy.deepcopy(USER)
    once = hc.merge(USER, PY, SCRIPT)
    assert USER == original  # 不改入参
    assert once["model"] == "opusplan"
    assert once["hooks"]["PostToolUse"] == USER["hooks"]["PostToolUse"]
    assert once["hooks"]["Stop"][0] == USER["hooks"]["Stop"][0]
    assert once["hooks"]["PreToolUse"][0] == USER["hooks"]["PreToolUse"][0]
    twice = hc.merge(once, PY, SCRIPT)
    assert twice == once
    assert len(shion_cmds(twice)) == len(hc.EVENTS)


def test_remove_restores_original():
    assert hc.remove(hc.merge(USER, PY, SCRIPT)) == USER
    assert hc.remove(hc.merge({}, PY, SCRIPT)) == {}
    assert hc.remove({"model": "x"}) == {"model": "x"}


def test_merge_rejects_bad_shapes():
    with pytest.raises(ValueError):
        hc.merge({"hooks": []}, PY, SCRIPT)
    with pytest.raises(ValueError):
        hc.merge({"hooks": {"Stop": {}}}, PY, SCRIPT)


def run_script(name, path):
    return subprocess.run(
        [sys.executable, str(TOOLS / name), "--settings", str(path)], capture_output=True, text=True
    )


def test_scripts_roundtrip_with_backup(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(USER), encoding="utf-8")
    assert run_script("install_hooks.py", p).returncode == 0
    installed = json.loads(p.read_text(encoding="utf-8"))
    assert len(shion_cmds(installed)) == len(hc.EVENTS)
    backups = list(tmp_path.glob("settings.json.shion-backup-*"))
    assert len(backups) == 1 and json.loads(backups[0].read_text(encoding="utf-8")) == USER
    assert run_script("uninstall_hooks.py", p).returncode == 0
    assert json.loads(p.read_text(encoding="utf-8")) == USER


def test_install_creates_missing_file(tmp_path):
    p = tmp_path / "sub" / "settings.local.json"
    assert run_script("install_hooks.py", p).returncode == 0
    assert len(shion_cmds(json.loads(p.read_text(encoding="utf-8")))) == len(hc.EVENTS)


def test_corrupt_json_not_touched(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("{坏", encoding="utf-8")
    for script in ("install_hooks.py", "uninstall_hooks.py"):
        r = run_script(script, p)
        assert r.returncode == 1 and "未被改写" in r.stderr
    assert p.read_text(encoding="utf-8") == "{坏"
    assert list(tmp_path.glob("*backup*")) == []


def test_default_python_is_absolute_venv_path(tmp_path):
    with pytest.raises(ValueError):
        hc.default_python(tmp_path)
    exe = tmp_path / ".venv" / "Scripts" / "python.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    assert hc.default_python(tmp_path) == exe.as_posix()
    assert hc.default_hook_script(tmp_path) == (tmp_path / "hooks" / "shion_hook.py").as_posix()


def test_old_quoted_and_shell_format_still_recognised_and_removed():
    old = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": 'python "C:/x/hooks/shion_hook.py" Stop'}]}]}}
    new = hc.merge(old, PY, SCRIPT)
    assert len(shion_cmds(new)) == len(hc.EVENTS)  # 旧条目被替换，不重复
    assert hc.remove(old) == {}


def test_uninstall_missing_or_unchanged_file_is_not_written(tmp_path):
    missing = tmp_path / "none.json"
    assert run_script("uninstall_hooks.py", missing).returncode == 0
    assert not missing.exists()
    p = tmp_path / "s.json"
    p.write_text('{"model":"x"}', encoding="utf-8")
    assert run_script("uninstall_hooks.py", p).returncode == 0
    assert p.read_text(encoding="utf-8") == '{"model":"x"}'
    assert list(tmp_path.glob("*backup*")) == []


def test_bom_settings_are_readable(tmp_path):
    p = tmp_path / "s.json"
    p.write_bytes(b"\xef\xbb\xbf" + b'{"model":"x"}')
    assert hc.load(p) == {"model": "x"}
