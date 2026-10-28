"""Official-style trust changes and third-party edits remain outside ownership."""
import copy
import json
import re

import pytest
import tomlkit

from tools import codex_config as C

COMMAND = ["C:/Shion/Shion.exe", "--codex-observer"]


def install(home):
    return C.install_plan(home, COMMAND, home / "data")


def official_trust(home, enabled=True):
    path = home / "config.toml"
    doc = tomlkit.parse(path.read_bytes().decode())
    hooks = doc.setdefault("hooks", {})
    states = hooks.setdefault("state", {})
    # Same source/event/group/handler key form reported by hooks/list. No real
    # client configuration or trust database is used by these simulations.
    for index, event in enumerate(C.hook_groups()):
        event_key = re.sub(r"(?<!^)(?=[A-Z])", "_", event).lower()
        key = f"{home / 'hooks.json'}:{event_key}:0:0"
        states[key] = {"enabled": enabled, "trusted_hash": "sha256:" + str(index) * 64}
    states["third-party-existing"] = {"enabled": False, "trusted_hash": "third-party-trust-marker"}
    path.write_bytes(tomlkit.dumps(doc).encode())
    return copy.deepcopy(doc.unwrap()["hooks"]["state"])


def add_foreign(home):
    path = home / "config.toml"
    path.write_bytes(path.read_bytes() + b'\n[mcp_servers.foreign]\ncommand="third-party-sensitive-marker"\n')
    path = home / "hooks.json"
    data = json.loads(path.read_bytes())
    data["description"] = "外部配置保留"
    data["hooks"]["Stop"].append({"hooks": [{"type": "command", "command": "foreign-tool"}]})
    data["hooks"]["Notification"] = [{"hooks": [{"type": "command", "command": "notification-tool"}]}]
    path.write_bytes(json.dumps(data, ensure_ascii=False, indent=2).encode())
    return data


@pytest.mark.parametrize("enabled", [True, False])
def test_normal_trust_and_third_party_append_survive_uninstall(tmp_path, enabled):
    home = tmp_path
    C.apply_plan(install(home))
    states = official_trust(home, enabled)
    foreign = add_foreign(home)
    assert not install(home).changes
    before = {name: C.read(home / name) for name in ("config.toml", "hooks.json")}
    removal = C.uninstall_plan(home)
    assert {name: C.read(home / name) for name in before} == before  # preview only
    C.apply_plan(removal)
    config = tomlkit.parse((home / "config.toml").read_bytes().decode()).unwrap()
    assert config["hooks"]["state"] == states
    assert config["mcp_servers"] == {"foreign": {"command": "third-party-sensitive-marker"}}
    hooks = json.loads((home / "hooks.json").read_bytes())
    assert hooks == {"description": foreign["description"], "hooks": {
        "Stop": [foreign["hooks"]["Stop"][-1]], "Notification": foreign["hooks"]["Notification"]}}
    assert not C.uninstall_plan(home).changes
    assert not C.recover(home)
    # Reconnect/install again, then remove it again without changing foreign data.
    uninstalled = {name: C.read(home / name) for name in before}
    C.apply_plan(install(home))
    assert not install(home).changes
    C.apply_plan(C.uninstall_plan(home))
    assert {name: C.read(home / name) for name in before} == uninstalled


def test_disable_and_reconnect_do_not_mutate_global_config(tmp_path, monkeypatch):
    from shion import chatgpt
    data = tmp_path / "data"
    monkeypatch.setattr(chatgpt, "observer_command", lambda: COMMAND)
    connection = chatgpt.ChatGPTConnection(data, tmp_path)
    C.apply_plan(connection.plan())
    official_trust(tmp_path)
    before = [(tmp_path / name).read_bytes() for name in ("config.toml", "hooks.json")]
    connection.toggle()
    assert not connection.enabled
    assert not connection.plan().changes
    connection.toggle()
    assert connection.enabled
    assert before == [(tmp_path / name).read_bytes() for name in ("config.toml", "hooks.json")]
    C.apply_plan(connection.plan(uninstall=True))


def test_adjacent_owned_members_after_original_foreign_group(tmp_path):
    foreign = {"hooks": [{"type": "command", "command": "original-foreign"}]}
    (tmp_path / "hooks.json").write_bytes(json.dumps({"hooks": {"Stop": [foreign]}}).encode())
    C.apply_plan(install(tmp_path))
    official_trust(tmp_path)
    added = add_foreign(tmp_path)
    C.apply_plan(C.uninstall_plan(tmp_path))
    assert json.loads((tmp_path / "hooks.json").read_bytes()) == {
        "description": added["description"], "hooks": {"Stop": [foreign, added["hooks"]["Stop"][-1]],
        "Notification": added["hooks"]["Notification"]}}


@pytest.mark.parametrize("change", ["duplicate", "modified", "extra_mcp_field", "scalar_type"])
def test_ambiguous_or_modified_ownership_stops(tmp_path, change):
    C.apply_plan(install(tmp_path))
    official_trust(tmp_path)
    if change == "extra_mcp_field":
        path = tmp_path / "config.toml"
        doc = tomlkit.parse(path.read_bytes().decode())
        doc["mcp_servers"][C.NAME]["enabled"] = False
        path.write_bytes(tomlkit.dumps(doc).encode())
    else:
        path = tmp_path / "hooks.json"
        doc = json.loads(path.read_bytes())
        if change == "duplicate":
            doc["hooks"]["Stop"].append(copy.deepcopy(doc["hooks"]["Stop"][0]))
        elif change == "scalar_type":
            doc["hooks"]["Stop"][0]["hooks"][0]["timeout"] = True
        else:
            doc["hooks"]["Stop"][0]["hooks"][0]["timeout"] = 20
        path.write_bytes(json.dumps(doc).encode())
    original = path.read_bytes()
    with pytest.raises(C.Conflict):
        C.uninstall_plan(tmp_path)
    assert path.read_bytes() == original


@pytest.mark.parametrize("crash_at", [1, 2, 3, 4])
def test_uninstall_wal_after_trust_changes_and_repeated_crash(tmp_path, monkeypatch, crash_at):
    class Crash(BaseException):
        pass
    C.apply_plan(install(tmp_path))
    official_trust(tmp_path)
    add_foreign(tmp_path)
    before = {name: C.read(tmp_path / name) for name in ("config.toml", "hooks.json")}
    proposal = C.uninstall_plan(tmp_path)
    real, calls = C.atomic, [0]
    def crash(path, data, staging, **kwargs):
        real(path, data, staging, **kwargs)
        calls[0] += 1
        if calls[0] == crash_at:
            raise Crash()
    monkeypatch.setattr(C, "atomic", crash)
    with pytest.raises(Crash):
        C.apply_plan(proposal)
    raw = C.transaction_path(tmp_path).read_bytes()
    assert b"third-party-sensitive-marker" not in raw
    assert b"third-party-trust-marker" not in raw
    assert "外部配置保留".encode() not in raw
    calls[0] = crash_at - 1
    with pytest.raises(Crash):
        C.recover(tmp_path)
    monkeypatch.setattr(C, "atomic", real)
    assert C.recover(tmp_path)
    assert not C.recover(tmp_path)
    assert {name: C.read(tmp_path / name) for name in before} == before
    C.apply_plan(C.uninstall_plan(tmp_path))


def test_external_write_after_preview_or_wal_always_stops(tmp_path, monkeypatch):
    class Crash(BaseException):
        pass
    C.apply_plan(install(tmp_path))
    official_trust(tmp_path)
    removal = C.uninstall_plan(tmp_path)
    path = tmp_path / "config.toml"
    path.write_bytes(path.read_bytes() + b"# after preview\n")
    with pytest.raises(C.Conflict):
        C.apply_plan(removal)
    real = C.atomic
    def crash(target, content, staging, **kwargs):
        real(target, content, staging, **kwargs)
        if target.name.endswith("transaction.json"):
            raise Crash()
    monkeypatch.setattr(C, "atomic", crash)
    with pytest.raises(Crash):
        C.apply_plan(C.uninstall_plan(tmp_path))
    path.write_bytes(path.read_bytes() + b"# during transaction\n")
    before = path.read_bytes()
    with pytest.raises(C.Conflict):
        C.recover(tmp_path)
    assert path.read_bytes() == before


def test_uninstall_wal_cannot_reinsert_unowned_configuration(tmp_path, monkeypatch):
    class Crash(BaseException):
        pass
    C.apply_plan(install(tmp_path))
    official_trust(tmp_path)
    real = C.atomic
    def crash(target, content, staging, **kwargs):
        real(target, content, staging, **kwargs)
        if target.name == "config.toml":
            raise Crash()
    monkeypatch.setattr(C, "atomic", crash)
    with pytest.raises(Crash):
        C.apply_plan(C.uninstall_plan(tmp_path))
    monkeypatch.setattr(C, "atomic", real)
    journal = C.transaction_path(tmp_path)
    record = json.loads(journal.read_bytes())
    current = (tmp_path / "config.toml").read_bytes()
    own = "".join(e["text"] for e in record["ownership"]["files"]["config.toml"]["edits"]).encode()
    foreign = current + own + b'\n[unexpected]\nvalue="must-never-be-inserted"\n'
    record["files"]["config.toml"] = C.insertion_record(current, foreign)
    journal.write_bytes(json.dumps(record).encode())
    with pytest.raises(C.Conflict, match="semantics changed"):
        C.recover(tmp_path)
    assert (tmp_path / "config.toml").read_bytes() == current
    assert journal.exists()


@pytest.mark.parametrize("broken", [None, [], {"version": 3, "identity": C.NAME, "files": None}])
def test_corrupt_ownership_is_a_safe_conflict(tmp_path, broken):
    C.apply_plan(install(tmp_path))
    path = C.ownership_path(tmp_path)
    path.write_text(json.dumps(broken))
    before = (tmp_path / "config.toml").read_bytes()
    with pytest.raises(C.Conflict):
        C.uninstall_plan(tmp_path)
    assert (tmp_path / "config.toml").read_bytes() == before


def test_unrelated_toml_nan_and_boolean_types_are_preserved(tmp_path):
    original = b'flag=true\nnumber=1\nvalue=nan\n'
    (tmp_path / "config.toml").write_bytes(original)
    C.apply_plan(install(tmp_path))
    official_trust(tmp_path)
    C.apply_plan(C.uninstall_plan(tmp_path))
    assert (tmp_path / "config.toml").read_bytes().startswith(original)
