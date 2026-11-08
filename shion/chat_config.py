"""Insert/remove only Shion member bytes; retain all surrounding JSON bytes."""
from base64 import b64decode, b64encode
import os
from pathlib import Path
import sys
import tempfile
import json


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def members(text, start):
    decoder = json.JSONDecoder()
    def ws(pos):
        while pos < len(text) and text[pos] in ' \r\n\t':
            pos += 1
        return pos
    pos = ws(start + 1)
    result = {}
    while text[pos] != '}':
        key_start = pos
        key, end = decoder.raw_decode(text, pos)
        pos = ws(end)
        assert text[pos] == ':'
        value_start = ws(pos + 1)
        _, value_end = decoder.raw_decode(text, value_start)
        pos = ws(value_end)
        comma = pos if text[pos] == ',' else None
        result[key] = (key_start, value_start, value_end, comma)
        if comma is None:
            break
        pos = ws(pos + 1)
    return result


def parse(raw):
    text = raw.decode('utf-8')
    start = 1 if text.startswith('\ufeff') else 0
    while start < len(text) and text[start] in ' \r\n\t':
        start += 1
    config = json.loads(text.lstrip('\ufeff'), object_pairs_hook=unique)
    if not isinstance(config, dict) or not isinstance(config.get('mcpServers', {}), dict):
        raise ValueError('Invalid config shape')
    return text, start, config


def insert(raw, entry):
    text, start, config = parse(raw)
    top = members(text, start)
    if 'mcpServers' in top:
        start = top['mcpServers'][1]
        container = config['mcpServers']
        if 'shion' in container:
            raise ValueError('shion already exists')
        addition = '"shion":' + json.dumps(entry, ensure_ascii=True)
    else:
        container = config
        addition = '"mcpServers":' + json.dumps({'shion': entry}, ensure_ascii=True)
    addition += ',' if container else ''
    offset = len(text[:start + 1].encode('utf-8'))
    payload = addition.encode('utf-8')
    result = raw[:offset] + payload + raw[offset:]
    assert result[:offset] + result[offset + len(payload):] == raw
    return result


def remove(raw, entry):
    text, start, config = parse(raw)
    if config.get('mcpServers', {}).get('shion') != entry:
        raise ValueError('shion entry changed')
    container_start = members(text, start)['mcpServers'][1]
    items = members(text, container_start)
    begin, _, end, comma = items['shion']
    if comma is not None:
        end = comma + 1
    elif len(items) > 1:
        previous = list(items).index('shion') - 1
        begin = list(items.values())[previous][3]
    return (text[:begin] + text[end:]).encode('utf-8')


CONFIG_NAME = "claude_desktop_config.json"


def candidates():
    """Possible locations are hints. Claude's Edit Config action confirms the profile."""
    paths = []
    if os.environ.get("LOCALAPPDATA"):
        root = Path(os.environ["LOCALAPPDATA"]) / "Claude-Data"
        paths.extend(sorted(root.glob("claude_*/" + CONFIG_NAME)))
    if os.environ.get("APPDATA"):
        paths.append(Path(os.environ["APPDATA"]) / "Claude" / CONFIG_NAME)
    return [path for path in paths if path.is_file()]


def chat_entry():
    command = Path(sys.executable)
    args = ["--chat-mcp"]
    if not getattr(sys, "frozen", False):
        if command.name.lower() == "pythonw.exe":
            command = command.with_name("python.exe")
        args.insert(0, str(Path(__file__).resolve().with_name("__main__.py")))
    if not command.is_file():
        raise ValueError("Missing MCP executable")
    return {"command": str(command), "args": args}


def write_checked(path, expected, new):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
    try:
        temporary.write_bytes(new)
        if expected is None:
            os.link(temporary, path)  # create only, including the receipt
        else:
            if path.read_bytes() != expected:
                raise ValueError("Configuration changed during update")
            os.replace(temporary, path)
        if path.read_bytes() != new:
            raise ValueError("Configuration verification failed")
    finally:
        temporary.unlink(missing_ok=True)


class ChatConnection:
    def __init__(self, data_dir):
        self.receipt = Path(data_dir) / "desktop-chat-backup.json"

    def connect(self, target):
        target = Path(target).resolve(strict=True)
        if target.name.lower() != CONFIG_NAME:
            raise ValueError("Unexpected configuration filename")
        original = target.read_bytes()
        entry = chat_entry()
        updated = insert(original, entry)
        backup = {"path": str(target), "entry": entry,
                  "original": b64encode(original).decode("ascii")}
        self.receipt.parent.mkdir(parents=True, exist_ok=True)
        write_checked(self.receipt, None, json.dumps(backup).encode("utf-8"))
        write_checked(target, original, updated)

    def disconnect(self):
        # Keep the receipt until the config write succeeds. An interrupted
        # install/removal can be retried without adopting a foreign entry.
        backup = json.loads(self.receipt.read_bytes())
        target = Path(backup["path"])
        if not target.is_absolute() or target.name.lower() != CONFIG_NAME:
            raise ValueError("Invalid backup target")
        original = b64decode(backup["original"], validate=True)
        entry = backup["entry"]
        installed = insert(original, entry)
        current = target.read_bytes()
        if current == installed:
            write_checked(target, current, original)
        elif "shion" in parse(current)[2].get("mcpServers", {}):
            write_checked(target, current, remove(current, entry))
        self.receipt.unlink()
