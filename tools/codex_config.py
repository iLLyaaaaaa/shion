"""Reviewable user-level Codex configuration transactions; never edits trust."""
from __future__ import annotations

import difflib
import hashlib
import json
import os
from pathlib import Path
from dataclasses import dataclass

import tomlkit

from shion.events import EVENTS
from shion import observer_files as secure

NAME = "shion_lifecycle_v1"
MANIFEST = ".shion-lifecycle-v1.json"
MAX_CONFIG = 2_000_000


class Conflict(ValueError):
    pass


def codex_home():
    value = os.environ.get("CODEX_HOME")
    path = Path(value).expanduser() if value else Path.home() / ".codex"
    if not path.is_absolute():
        raise Conflict("CODEX_HOME must be absolute; inspect the client's effective environment")
    return path.resolve()


def read(path):
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise Conflict(f"Unsupported configuration path: {path}")
    if not path.exists():
        return None
    if path.stat().st_size > MAX_CONFIG:
        raise Conflict("Configuration is too large")
    return path.read_bytes()


def digest(value):
    return hashlib.sha256(value).hexdigest() if value is not None else None


def atomic(path, data, staging):
    secure.replace_private(path, data, preserve_security=path.name in ("config.toml", "hooks.json"))


def private_location(home, private_dir=None):
    root = Path(private_dir) if private_dir is not None else Path(home) / ".shion-observer-v2"
    secure.reject_reparse(root)
    return root.absolute()


def ownership_path(home, private_dir=None):
    root = private_location(home, private_dir)
    key = hashlib.sha256(str(Path(home).resolve()).casefold().encode()).hexdigest()[:24]
    return root / (key + MANIFEST)


def read_ownership(home, private_dir=None):
    if (Path(home) / MANIFEST).exists():
        raise Conflict("Legacy ownership record requires an explicitly reviewed migration")
    path = ownership_path(home, private_dir)
    return secure.read_private(path) if path.exists() else None


def hook_groups():
    out = {}
    for event in EVENTS:
        projection = {"event": event, "source": "global", "session_id": "${session_id}"}
        if event != "SessionStart":
            projection["turn_id"] = "${turn_id}"
        if event in ("PreToolUse", "PostToolUse"):
            projection["tool_use_id"] = "${tool_use_id}"
        group = {"hooks": [{"type": "mcp_tool", "server": NAME, "tool": "observe_lifecycle",
                            "input": projection, "timeout": 1}]}
        out[event] = [group]
    return out


def json_spans(text):
    """Locate object/array boundaries without reserializing any existing byte."""
    decoder = json.JSONDecoder(object_pairs_hook=_unique_pairs)
    decoder.decode(text)
    spans = {}

    def skip(i):
        while i < len(text) and text[i].isspace():
            i += 1
        return i

    def walk(i, path):
        i = skip(i)
        start = i
        if text[i] == "{":
            i = skip(i + 1)
            while text[i] != "}":
                key, i = decoder.raw_decode(text, i)
                i = walk(skip(i) + 1, path + (key,))
                i = skip(i)
                if text[i] == ",":
                    i = skip(i + 1)
            i += 1
        elif text[i] == "[":
            i = skip(i + 1)
            n = 0
            while text[i] != "]":
                i = skip(walk(i, path + (n,)))
                n += 1
                if text[i] == ",":
                    i = skip(i + 1)
            i += 1
        else:
            _, i = decoder.raw_decode(text, i)
        spans[path] = (start, i)
        return i

    walk(0, ())
    return spans


def _unique_pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise Conflict("Duplicate JSON key")
        out[key] = value
    return out


def add_hooks(text):
    data = json.loads(text, object_pairs_hook=_unique_pairs)
    if not isinstance(data, dict):
        raise Conflict("hooks.json must be an object")
    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        raise Conflict("Invalid hooks table")
    if NAME in text:
        raise Conflict("Shion hook identity already exists without matching ownership")
    # Validate all third-party groups without changing or trusting them.
    from tools.hooks_config import validate
    validate(data)
    spans = json_spans(text)
    inserts = []
    if "hooks" not in data:
        inserts.append((spans[()][1] - 1, ("," if data else "") + '\n"hooks": ' + json.dumps(hook_groups())))
    else:
        additions = {}
        for event, groups in hook_groups().items():
            if event in hooks:
                inserts.append((spans[("hooks", event)][1] - 1,
                                ("," if hooks[event] else "") + json.dumps(groups[0])))
            else:
                additions[event] = groups
        if additions:
            inserts.append((spans[("hooks",)][1] - 1,
                            ("," if hooks else "") + json.dumps(additions)[1:-1]))
    for offset, value in sorted(inserts, reverse=True):
        text = text[:offset] + value + text[offset:]
    json.loads(text)
    return text


@dataclass(frozen=True)
class Change:
    path: Path
    before: bytes | None
    after: bytes | None


@dataclass
class Plan:
    home: Path
    changes: list[Change]
    action: str
    private_dir: Path

    def diff(self):
        return "\n".join("".join(difflib.unified_diff(
            (c.before or b"").decode("utf-8").splitlines(True),
            (c.after or b"").decode("utf-8").splitlines(True),
            fromfile=str(c.path), tofile=str(c.path) + " (proposed)", n=0))
            for c in self.changes if not c.path.name.endswith(MANIFEST))


def install_plan(home: Path, command: list[str], data_dir: Path, private_dir=None):
    secure.reject_reparse(home)
    home = home.resolve()
    private_dir = private_location(home, private_dir)
    manifest = ownership_path(home, private_dir)
    owned_raw = read_ownership(home, private_dir)
    if owned_raw is not None:
        owned = json.loads(owned_raw)
        if owned.get("identity") != NAME or set(owned.get("files", {})) != {"config.toml", "hooks.json"}:
            raise Conflict("Invalid ownership manifest")
        # Normal trust review may append records. Validate owned fragments rather
        # than requiring unrelated user/trust configuration to remain unchanged.
        uninstall_plan(home, private_dir)
        for filename, item in owned["files"].items():
            if filename == "config.toml":
                actual = tomlkit.parse(read(home / filename).decode("utf-8"))["mcp_servers"][NAME]
                if (actual["command"] != command[0]
                        or actual["args"] != command[1:] + ["--data-dir", str(data_dir.resolve())]):
                    raise Conflict("Installed observer location differs; review migration first")
        return Plan(home, [], "install", private_dir)
    config_path, hooks_path = home / "config.toml", home / "hooks.json"
    before_config, before_hooks = read(config_path), read(hooks_path)
    original = (before_config or b"").decode("utf-8")
    config = tomlkit.parse(original)
    if NAME in config.get("mcp_servers", {}) or NAME in original:
        raise Conflict("MCP identity conflict")
    if config.get("features", {}).get("hooks") is False or config.get("features", {}).get("codex_hooks") is False:
        raise Conflict("Hooks are disabled; enable through normal client settings first")
    # Parse with tomlkit, append a new table to preserve every existing byte.
    addition = tomlkit.document()
    addition["mcp_servers"] = {NAME: {"command": command[0],
        "args": command[1:] + ["--data-dir", str(data_dir.resolve())],
        "startup_timeout_sec": 5, "tool_timeout_sec": 1}}
    config_text = original + ("\n" if original and not original.endswith("\n") else "") + "\n" + tomlkit.dumps(addition)
    parsed = tomlkit.parse(config_text)
    if parsed["mcp_servers"][NAME]["command"] != command[0]:
        raise Conflict("MCP validation failed")
    hooks_text = add_hooks((before_hooks or b"{}\n").decode("utf-8"))
    changes = [Change(config_path, before_config, config_text.encode("utf-8")),
               Change(hooks_path, before_hooks, hooks_text.encode("utf-8"))]
    files = {c.path.name: insertion_record(c.before, c.after) for c in changes}
    record = {"version": 2, "identity": NAME, "files": files}
    changes.append(Change(manifest, None, json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8")))
    return Plan(home, changes, "install", private_dir)


def insertion_record(before, after):
    # Exact offsets, never an original user-config snapshot. SequenceMatcher is
    # used only on our just-generated insertion, never to infer ownership later.
    edits = []
    for tag, a, b, c, d in difflib.SequenceMatcher(None, before or b"", after, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if tag != "insert":
            raise Conflict("Installation must only insert bytes")
        text = after[c:d].decode("utf-8")
        edits.append({"offset": a, "text": text, "sha256": digest(after[c:d])})
    return {"before": digest(before), "after": digest(after), "length": len(before or b""), "edits": edits}


def transform(current, item, reverse=False):
    expected, target = ("after", "before") if reverse else ("before", "after")
    if digest(current) != item[expected]:
        raise Conflict("External modification; automatic recovery/removal stopped")
    result = current or b""
    delta = 0
    edits = []
    for edit in item["edits"]:
        fragment = edit["text"].encode("utf-8")
        if digest(fragment) != edit["sha256"]:
            raise Conflict("Fragment evidence damaged")
        offset = edit["offset"]
        if type(offset) is not int or offset < 0 or offset > item["length"]:
            raise Conflict("Invalid fragment offset")
        edits.append((offset + delta if reverse else offset, fragment))
        delta += len(fragment)
    for offset, fragment in reversed(edits):
        if reverse:
            if result[offset:offset + len(fragment)] != fragment:
                raise Conflict("Ambiguous fragment")
            result = result[:offset] + result[offset + len(fragment):]
        else:
            result = result[:offset] + fragment + result[offset:]
    if item[target] is None:
        if result:
            raise Conflict("Unexpected remaining bytes")
        result = None
    if digest(result) != item[target]:
        raise Conflict("Result hash mismatch")
    return result


def validate_semantics(filename, before, after):
    """Prove the only semantic difference is our exact MCP/hook definition."""
    import copy
    if filename == "config.toml":
        original = tomlkit.parse((before or b"").decode("utf-8")).unwrap()
        installed = tomlkit.parse((after or b"").decode("utf-8")).unwrap()
        stripped = copy.deepcopy(installed)
        server = stripped.get("mcp_servers", {}).pop(NAME, None)
        if not isinstance(server, dict) or set(server) != {"command", "args", "startup_timeout_sec", "tool_timeout_sec"}:
            raise Conflict("Invalid owned MCP table")
        if "mcp_servers" not in original and not stripped.get("mcp_servers"):
            stripped.pop("mcp_servers", None)
    else:
        original = json.loads(before or b"{}", object_pairs_hook=_unique_pairs)
        installed = json.loads(after or b"{}", object_pairs_hook=_unique_pairs)
        from tools.hooks_config import validate
        validate(original)
        validate(installed)
        stripped = copy.deepcopy(installed)
        for event, groups in hook_groups().items():
            actual = stripped.get("hooks", {}).get(event, [])
            if actual.count(groups[0]) != 1:
                raise Conflict("Owned Hook missing or ambiguous")
            actual.remove(groups[0])
            if event not in original.get("hooks", {}) and not actual:
                stripped["hooks"].pop(event)
        if "hooks" not in original and not stripped.get("hooks"):
            stripped.pop("hooks", None)
    if stripped != original:
        raise Conflict("Unrelated configuration semantics changed")


def uninstall_plan(home, private_dir=None):
    secure.reject_reparse(home)
    home = Path(home).resolve()
    private_dir = private_location(home, private_dir)
    raw = read_ownership(home, private_dir)
    if raw is None:
        if any(NAME.encode() in (read(home / f) or b"") for f in ("config.toml", "hooks.json")):
            raise Conflict("Ownership evidence missing; manual review required")
        return Plan(home, [], "uninstall", private_dir)
    record = json.loads(raw, object_pairs_hook=_unique_pairs)
    if record.get("version") != 2 or record.get("identity") != NAME or set(record.get("files", {})) != {"config.toml", "hooks.json"}:
        raise Conflict("Invalid or legacy ownership manifest; manual review required")
    changes = []
    for filename, item in record["files"].items():
        current = read(home / filename)
        restored = transform(current, item, reverse=True)
        validate_semantics(filename, restored, current)
        changes.append(Change(home / filename, current, restored))
    changes.append(Change(ownership_path(home, private_dir), raw, None))
    return Plan(home, changes, "uninstall", private_dir)


def transaction_path(home, private_dir=None):
    return ownership_path(home, private_dir).with_suffix(".transaction.json")


def recover(home, private_dir=None):
    """Rollback a WAL, idempotently, including a crash during this recovery.

    Preflight EVERY file before changing any. An absent WAL is not permission
    to guess; an extant lock without a WAL always requires manual review.
    """
    secure.reject_reparse(home)
    home = Path(home).resolve()
    root = private_location(home, private_dir)
    journal = transaction_path(home, root)
    lock = journal.with_suffix(".lock")
    if not journal.exists():
        if lock.exists():
            raise Conflict("Transaction evidence missing; manual review required")
        return False
    record = json.loads(read(journal), object_pairs_hook=_unique_pairs)
    if record.get("version") != 2 or record.get("home") != str(home) or record.get("action") not in ("install", "uninstall"):
        raise Conflict("Invalid transaction evidence")
    files = record["files"]
    if set(files) != {"config.toml", "hooks.json"}:
        raise Conflict("Invalid transaction targets")
    if record.get("ownership") != {"version": 2, "identity": NAME, "files": files}:
        raise Conflict("Inconsistent transaction ownership")
    reverse = record["action"] == "install"
    changes = []
    for filename, item in files.items():
        current = read(home / filename)
        target = item["before" if reverse else "after"]
        source = item["after" if reverse else "before"]
        if digest(current) == target:
            continue
        if digest(current) != source:
            raise Conflict("External edit prevents recovery")
        restored = transform(current, item, reverse=reverse)
        validate_semantics(filename, restored if reverse else current, current if reverse else restored)
        changes.append(Change(home / filename, current, restored))
    manifest = ownership_path(home, root)
    owned = json.dumps(record["ownership"], ensure_ascii=False, indent=2).encode("utf-8")
    current_owned = read(manifest)
    if current_owned not in (None, owned):
        raise Conflict("Ownership evidence changed")
    # An OS/process crash can leave a fully or partly written staging file.
    # Only a complete known image is safe to discard; partial/foreign content
    # is deliberately left for manual review, never guessed away.
    staging = []
    targets = [(home / name, (item["before"], item["after"])) for name, item in files.items()]
    targets.append((manifest, (digest(owned),)))
    for path, hashes in targets:
        temporary = secure.staging_path(path)
        content = read(temporary)
        if content is not None:
            if digest(content) not in hashes:
                raise Conflict("Ambiguous staging file; manual review required")
            staging.append((temporary, content))
    for temporary, content in staging:
        if read(temporary) != content:
            raise Conflict("Staging file changed during recovery")
        temporary.unlink()
    for change in changes:
        if read(change.path) != change.before:
            raise Conflict("Concurrent edit during recovery")
        atomic(change.path, change.after, root)
    atomic(manifest, None if reverse else owned, root)
    # WAL is the authority. Remove lock first so interrupted cleanup is repeatable.
    lock.unlink(missing_ok=True)
    journal.unlink()
    return True


def apply_plan(plan: Plan):
    if not plan.changes:
        return None
    plan.home.mkdir(parents=True, exist_ok=True)
    root = secure.ensure_directory(plan.private_dir)
    journal = transaction_path(plan.home, root)
    lock = journal.with_suffix(".lock")
    if journal.exists() or lock.exists():
        raise Conflict("Pending transaction; explicitly recover before retry")
    for change in plan.changes:
        if read(change.path) != change.before:
            raise Conflict("Configuration changed after preview")
    manifest_change = plan.changes[-1]
    owned = json.loads(manifest_change.after if plan.action == "install" else manifest_change.before)
    for change in plan.changes[:-1]:
        validate_semantics(change.path.name, change.before if plan.action == "install" else change.after,
                           change.after if plan.action == "install" else change.before)
    secure.write_new(lock, b"")
    record = {"version": 2, "home": str(plan.home), "action": plan.action,
              "files": owned["files"], "ownership": owned}
    try:
        # Flush the complete WAL before the first configuration mutation.
        atomic(journal, json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8"), root)
        for change in plan.changes:
            if read(change.path) != change.before:
                raise Conflict("Concurrent configuration edit")
            atomic(change.path, change.after, root)
            if read(change.path) != change.after:
                raise Conflict("Post-write verification failed")
        # Commit marker is deleting WAL. A crash before this point rolls back.
        lock.unlink()
        journal.unlink()
    except Exception:
        recover(plan.home, root)
        raise
    return None


def inspect(home, private_dir=None):
    """Read-only structure summary; never disclose notify arguments or secrets."""
    config = tomlkit.parse((read(home / "config.toml") or b"").decode("utf-8"))
    hooks = json.loads(read(home / "hooks.json") or b"{}")
    state = config.get("hooks", {}).get("state", {})
    return {"home": str(home), "installed": read_ownership(home, private_dir) is not None,
            "mcp_registered": NAME in config.get("mcp_servers", {}),
            "mcp_names": list(config.get("mcp_servers", {})), "notify_present": "notify" in config,
            "hooks_file_present": (home / "hooks.json").exists(),
            "hook_events": list(hooks.get("hooks", {})),
            "inline_hook_events": [k for k in config.get("hooks", {}) if k != "state"],
            "disabled_trust_records": sum(isinstance(v, dict) and v.get("enabled") is False for v in state.values()),
            "trust": "verify exact definitions in /hooks", "actual_events": "check running Shion",
            "features_hooks": config.get("features", {}).get("hooks", "default"),
            "hashes": {n: digest(read(home / n)) for n in ("config.toml", "hooks.json")}}


def audit_layers(home, project):
    """Inspect discoverable disk layers without opening sessions, auth or history.

    CLI flags, remote managed policy and another process's environment cannot be
    inferred from these files. Report that limitation instead of guessing.
    """
    paths = {home / "config.toml", home / "hooks.json", home / "requirements.toml"}
    paths.update(home.glob("*.config.toml"))
    paths.update(home.glob("*.hooks.json"))
    for parent in (project.resolve(), *project.resolve().parents):
        paths.update((parent / ".codex" / name) for name in ("config.toml", "hooks.json"))
    rows = []
    for path in sorted(paths):
        raw = read(path)
        if raw is None:
            continue
        data = json.loads(raw) if path.suffix == ".json" else tomlkit.parse(raw.decode("utf-8"))
        hooks = data.get("hooks", {})
        rows.append({"path": str(path), "sha256": digest(raw),
                     "notify_present": "notify" in data,
                     "mcp_names": list(data.get("mcp_servers", {})),
                     "hook_events": [k for k in hooks if k != "state"],
                     "shion_identity_present": NAME.encode() in raw,
                     "hooks_disabled": data.get("features", {}).get("hooks") is False})
    return {"files": rows, "runtime_overrides": "unverified: client flags, selected profile, managed policy, client environment"}
