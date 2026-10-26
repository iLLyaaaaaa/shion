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
    backup = C.apply_plan(proposal)
    assert (backup / "config.toml").read_bytes() == original
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
    def fail(path, data):
        calls[0] += 1
        if calls[0] == 2:
            raise OSError("simulated failure")
        return original_atomic(path, data)
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
    assert not plan(tmp_path).changes
    C.apply_plan(C.uninstall_plan(tmp_path))
    assert path.read_text() == addition


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
