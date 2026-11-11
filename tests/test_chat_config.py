"""Claude Desktop configuration transactions, using isolated files only."""
import json

import pytest

from shion.chat_config import CONFIG_NAME, ChatConnection, candidates, insert, remove, write_checked


@pytest.mark.parametrize("original", [
    b'{}', b' {  }\r\n',
    b'\xef\xbb\xbf{ "preferences":{"x":1e2}, "a":"\\u4e2d" }',
    b'{"mcpServers": {  }, "a":1}',
    b'{"mcpServers":{"old":{"command":"other"}},"a":1}',
])
def test_connect_and_disconnect_restore_exact_bytes(tmp_path, original):
    target = tmp_path / CONFIG_NAME
    target.write_bytes(original)
    connection = ChatConnection(tmp_path / "data")
    connection.connect(target)
    config = json.loads(target.read_bytes().decode("utf-8-sig"))
    assert config["mcpServers"]["shion"]["args"][-1] == "--chat-mcp"
    connection.disconnect()
    assert target.read_bytes() == original
    assert not connection.receipt.exists()


@pytest.mark.parametrize("changed", [False, True])
def test_disconnect_preserves_other_edits_and_refuses_changed_entry(tmp_path, changed):
    target = tmp_path / CONFIG_NAME
    target.write_bytes(b'{}')
    connection = ChatConnection(tmp_path / "data")
    connection.connect(target)
    config = json.loads(target.read_bytes())
    config["preferences"] = {"keep": True}
    config["mcpServers"]["other"] = {"command": "keep"}
    if changed:
        config["mcpServers"]["shion"]["command"] = "changed"
    raw = json.dumps(config).encode()
    target.write_bytes(raw)
    if changed:
        with pytest.raises(ValueError):
            connection.disconnect()
        assert target.read_bytes() == raw
        assert connection.receipt.exists()
    else:
        connection.disconnect()
        assert target.read_bytes() == remove(raw, config["mcpServers"]["shion"])


@pytest.mark.parametrize("damage", ["deleted", "broken", "entry_changed"])
def test_forget_drops_receipt_without_touching_config(tmp_path, damage):
    target = tmp_path / CONFIG_NAME
    target.write_bytes(b'{}')
    connection = ChatConnection(tmp_path / "data")
    connection.connect(target)
    if damage == "deleted":
        target.unlink()
    elif damage == "broken":
        target.write_bytes(b'{broken')
    else:
        config = json.loads(target.read_bytes())
        config["mcpServers"]["shion"]["command"] = "mine"
        target.write_bytes(json.dumps(config).encode())
    before = target.read_bytes() if target.exists() else None
    with pytest.raises((OSError, ValueError)):
        connection.disconnect()
    assert connection.receipt.exists()  # 失败时回执仍在，可以重试
    connection.forget()
    assert not connection.receipt.exists()
    assert (target.read_bytes() if target.exists() else None) == before
    connection.forget()  # 再次放弃也不报错


@pytest.mark.parametrize("raw", [
    b'{"mcpServers":{"shion":{}}}', b'{"mcpServers":[]}',
    b'{"x":1,"x":2}', b'{broken', b'[]', b'',
])
def test_invalid_or_foreign_config_is_untouched(tmp_path, raw):
    target = tmp_path / CONFIG_NAME
    target.write_bytes(raw)
    connection = ChatConnection(tmp_path / "data")
    with pytest.raises(ValueError):
        connection.connect(target)
    assert target.read_bytes() == raw
    assert not connection.receipt.exists()


def test_interrupted_install_and_restore_can_be_retried(tmp_path, monkeypatch):
    from shion import chat_config
    target = tmp_path / CONFIG_NAME
    target.write_bytes(b'{}')
    connection = ChatConnection(tmp_path / "data")
    real_write = write_checked

    def fail_target(path, expected, new):
        if path == target:
            raise OSError("interrupted")
        real_write(path, expected, new)

    monkeypatch.setattr(chat_config, "write_checked", fail_target)
    with pytest.raises(OSError):
        connection.connect(target)
    assert connection.receipt.exists() and target.read_bytes() == b'{}'
    monkeypatch.setattr(chat_config, "write_checked", real_write)
    connection.disconnect()
    connection.connect(target)
    monkeypatch.setattr(chat_config, "write_checked", fail_target)
    with pytest.raises(OSError):
        connection.disconnect()
    monkeypatch.setattr(chat_config, "write_checked", real_write)
    connection.disconnect()
    assert target.read_bytes() == b'{}'


def test_compare_before_write_and_exclusive_backup(tmp_path):
    target = tmp_path / CONFIG_NAME
    target.write_bytes(b'{"other":1}')
    with pytest.raises(ValueError):
        write_checked(target, b'{}', b'{"bad":1}')
    assert target.read_bytes() == b'{"other":1}'
    connection = ChatConnection(tmp_path / "data")
    connection.connect(target)
    backup = connection.receipt.read_bytes()
    target.write_bytes(b'{}')
    with pytest.raises(FileExistsError):
        connection.connect(target)
    assert connection.receipt.read_bytes() == backup
    assert target.read_bytes() == b'{}'


def test_candidates_only_use_isolated_roots(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    paths = [tmp_path / "local" / "Claude-Data" / "claude_active" / CONFIG_NAME,
             tmp_path / "roaming" / "Claude" / CONFIG_NAME]
    for path in paths:
        path.parent.mkdir(parents=True)
        path.write_bytes(b'{}')
    assert candidates() == paths
