import json
from pathlib import Path

import pytest
import tomlkit

from tools import codex_config as C


def plan(home):
    return C.install_plan(home, ["C:/Program Files/python.exe", "-B", "C:/Shion/observer.py"], home / "data")


def test_install_repeat_uninstall_preserves_every_original_byte(tmp_path):
    original = b'# personal comment\r\nnotify = ["custom", "keep"]\r\n\n[mcp_servers.other]\ncommand = "other" # stay\n'
    hooks = b'{\n "description": "keep order", "hooks": {"Stop": [{"hooks": [{"type":"command","command":"other"}]}]}\n}\n'
    (tmp_path / "config.toml").write_bytes(original)
    (tmp_path / "hooks.json").write_bytes(hooks)
    proposal = plan(tmp_path)
    assert (tmp_path / "config.toml").read_bytes() == original
    assert "shion_lifecycle_v1" in proposal.diff()
    C.apply_plan(proposal)
    assert original not in C.read_ownership(tmp_path)
    assert not plan(tmp_path).changes
    C.apply_plan(C.uninstall_plan(tmp_path))
    assert (tmp_path / "config.toml").read_bytes() == original
    assert (tmp_path / "hooks.json").read_bytes() == hooks


def test_fresh_install_and_uninstall(tmp_path):
    C.apply_plan(plan(tmp_path))
    data = tomlkit.parse((tmp_path / "config.toml").read_text())
    assert data["mcp_servers"][C.NAME]["args"][-2] == "--data-dir"
    C.apply_plan(C.uninstall_plan(tmp_path))
    assert not (tmp_path / "config.toml").exists()
    assert not (tmp_path / "hooks.json").exists()


def test_preview_race_and_name_conflict(tmp_path):
    proposal = plan(tmp_path)
    (tmp_path / "config.toml").write_text("# concurrent edit\n")
    with pytest.raises(C.Conflict):
        C.apply_plan(proposal)
    assert not (tmp_path / "hooks.json").exists()
    (tmp_path / "config.toml").write_text('[mcp_servers.shion_lifecycle_v1]\ncommand="unknown"\n')
    with pytest.raises(C.Conflict):
        plan(tmp_path)


def test_mid_transaction_failure_rolls_back(tmp_path, monkeypatch):
    proposal = plan(tmp_path)
    original_atomic = C.atomic
    calls = [0]
    def fail(path, data, staging):
        calls[0] += 1
        if calls[0] == 2:
            raise OSError("simulated failure")
        return original_atomic(path, data, staging)
    monkeypatch.setattr(C, "atomic", fail)
    with pytest.raises(OSError):
        C.apply_plan(proposal)
    assert not (tmp_path / "config.toml").exists()
    assert not (tmp_path / C.MANIFEST).exists()


def test_uninstall_preserves_new_trust_and_unrelated_config(tmp_path):
    C.apply_plan(plan(tmp_path))
    path = tmp_path / "config.toml"
    addition = '\n[hooks.state.test]\nenabled = false\ntrusted_hash = "do-not-touch"\n'
    path.write_bytes(path.read_bytes() + addition.encode())
    with pytest.raises(C.Conflict):
        C.uninstall_plan(tmp_path)
    assert path.read_bytes().endswith(addition.encode())


def test_uninstall_refuses_modified_ownership(tmp_path):
    C.apply_plan(plan(tmp_path))
    path = tmp_path / "hooks.json"
    path.write_text(path.read_text().replace('"timeout": 1', '"timeout": 20'))
    before = path.read_bytes()
    with pytest.raises(C.Conflict):
        C.uninstall_plan(tmp_path)
    assert path.read_bytes() == before


def test_disabled_and_duplicate_keys_refused(tmp_path):
    (tmp_path / "config.toml").write_text('[features]\nhooks=false\n')
    with pytest.raises(C.Conflict):
        plan(tmp_path)
    with pytest.raises(C.Conflict):
        C.add_hooks('{"hooks":{},"hooks":{}}')


def test_invalid_manifest_cannot_claim_installed(tmp_path):
    (tmp_path / C.MANIFEST).write_text('{"files": {}}')
    with pytest.raises(C.Conflict):
        plan(tmp_path)


class Crash(BaseException):
    pass


@pytest.mark.parametrize("action", ["install", "uninstall"])
@pytest.mark.parametrize("crash_at", [1, 2, 3, 4])
def test_crash_and_crash_during_recovery(tmp_path, monkeypatch, action, crash_at):
    original = b'# private-user-setting\nnotify=["keep"]\n'
    (tmp_path / "config.toml").write_bytes(original)
    if action == "uninstall":
        C.apply_plan(plan(tmp_path))
    before = {name: C.read(tmp_path / name) for name in ("config.toml", "hooks.json")}
    proposal = plan(tmp_path) if action == "install" else C.uninstall_plan(tmp_path)
    real = C.atomic
    calls = [0]
    def crash(path, data, staging):
        real(path, data, staging)
        calls[0] += 1
        if calls[0] == crash_at:
            raise Crash()
    monkeypatch.setattr(C, "atomic", crash)
    with pytest.raises(Crash):
        C.apply_plan(proposal)
    journal = C.transaction_path(tmp_path)
    assert original not in journal.read_bytes()
    calls[0] = crash_at - 1
    with pytest.raises(Crash):
        C.recover(tmp_path)
    monkeypatch.setattr(C, "atomic", real)
    assert C.recover(tmp_path)
    assert not C.recover(tmp_path)
    assert {name: C.read(tmp_path / name) for name in before} == before


def test_missing_wal_or_external_edit_never_guesses(tmp_path, monkeypatch):
    real = C.atomic
    def crash(path, data, staging):
        real(path, data, staging)
        if path.name == "config.toml":
            raise Crash()
    monkeypatch.setattr(C, "atomic", crash)
    with pytest.raises(Crash):
        C.apply_plan(plan(tmp_path))
    monkeypatch.setattr(C, "atomic", real)
    config = tmp_path / "config.toml"
    config.write_bytes(config.read_bytes() + b"# outside\n")
    before = config.read_bytes()
    with pytest.raises(C.Conflict):
        C.recover(tmp_path)
    assert config.read_bytes() == before
    C.transaction_path(tmp_path).unlink()
    with pytest.raises(C.Conflict):
        C.recover(tmp_path)
    assert config.read_bytes() == before


def test_missing_ownership_and_semantic_drift(tmp_path):
    C.apply_plan(plan(tmp_path))
    C.ownership_path(tmp_path).unlink()
    with pytest.raises(C.Conflict):
        C.uninstall_plan(tmp_path)
    with pytest.raises(C.Conflict):
        C.validate_semantics("config.toml", b'x=1\n', b'x=2\n[mcp_servers.shion_lifecycle_v1]\ncommand="x"\nargs=[]\nstartup_timeout_sec=5\ntool_timeout_sec=1\n')


def test_all_tool_hooks_have_no_matcher():
    for event in ("PreToolUse", "PostToolUse", "PermissionRequest"):
        assert "matcher" not in C.hook_groups()[event][0]


@pytest.mark.parametrize("during_recovery", [False, True])
def test_real_process_termination_with_staging(tmp_path, during_recovery):
    import os
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[1]
    original = b'# user content not stored in ownership\nnotify=["keep"]\n'
    (tmp_path / "config.toml").write_bytes(original)
    script = '''
import os, sys
from pathlib import Path
from tools import codex_config as C
home = Path(sys.argv[1])
real = C.secure._replace
def crash(source, target, preserve_security=False):
    if Path(target).name == "config.toml":
        os._exit(73)
    real(source, target, preserve_security)
C.secure._replace = crash
if sys.argv[2] == "recover":
    C.recover(home)
else:
    C.apply_plan(C.install_plan(home, ["C:/Shion/Shion.exe", "--codex-observer"], home / "data"))
'''
    env = dict(os.environ, PYTHONPATH=str(root))
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), "install"], cwd=root, env=env, timeout=10)
    assert result.returncode == 73
    staged = C.secure.staging_path(tmp_path / "config.toml")
    assert staged.exists()
    if during_recovery:
        # Simulate replacement committed just before the crash; now inverse
        # recovery itself is killed with its complete staging image on disk.
        staged.replace(tmp_path / "config.toml")
        result = subprocess.run([sys.executable, "-c", script, str(tmp_path), "recover"], cwd=root, env=env, timeout=10)
        assert result.returncode == 73
    assert C.recover(tmp_path)
    assert not C.recover(tmp_path)
    assert (tmp_path / "config.toml").read_bytes() == original
    assert not staged.exists()


def test_partial_stage_requires_manual_review(tmp_path, monkeypatch):
    real = C.atomic
    def crash(path, data, staging):
        real(path, data, staging)
        if path.name.endswith("transaction.json"):
            raise Crash()
    monkeypatch.setattr(C, "atomic", crash)
    with pytest.raises(Crash):
        C.apply_plan(plan(tmp_path))
    temporary = C.secure.staging_path(tmp_path / "config.toml")
    temporary.write_bytes(b"partial")
    with pytest.raises(C.Conflict):
        C.recover(tmp_path)
    assert temporary.read_bytes() == b"partial"
    assert not (tmp_path / "config.toml").exists()


def test_existing_windows_config_dacl_is_preserved(tmp_path):
    import os
    import subprocess
    if os.name != "nt":
        pytest.skip("Windows native replacement")
    path = tmp_path / "config.toml"
    path.write_bytes(b'# preserve file permissions\n')
    env = dict(os.environ, SHION_TEST_CONFIG=str(path))
    def powershell(script):
        return subprocess.check_output(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                                       env=env, text=True, timeout=15).strip()
    powershell('$ErrorActionPreference="Stop"; $p=$env:SHION_TEST_CONFIG; $a=[System.IO.File]::GetAccessControl($p); $a.SetAccessRuleProtection($true,$true); [System.IO.File]::SetAccessControl($p,$a)')
    query = '[System.IO.File]::GetAccessControl($env:SHION_TEST_CONFIG).GetSecurityDescriptorSddlForm([System.Security.AccessControl.AccessControlSections]::Access)'
    before = powershell(query)
    C.apply_plan(plan(tmp_path))
    assert powershell(query) == before
    C.apply_plan(C.uninstall_plan(tmp_path))
    assert powershell(query) == before
