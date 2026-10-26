"""Reviewable user-level Codex configuration transactions; never edits trust."""
from __future__ import annotations

import difflib
import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid
from dataclasses import dataclass

import tomlkit

from shion.events import EVENTS

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


def atomic(path, data):
    if data is None:
        path.unlink(missing_ok=True)
        return
    fd, name = tempfile.mkstemp(prefix=".shion-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


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
        if event in ("PreToolUse", "PostToolUse", "PermissionRequest"):
            group["matcher"] = "Bash|apply_patch"
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

    def diff(self):
        return "\n".join("".join(difflib.unified_diff(
            (c.before or b"").decode("utf-8").splitlines(True),
            (c.after or b"").decode("utf-8").splitlines(True),
            fromfile=str(c.path), tofile=str(c.path) + " (proposed)", n=0))
            for c in self.changes if c.path.name != MANIFEST)


def install_plan(home: Path, command: list[str], data_dir: Path):
    home = home.resolve()
    manifest = home / MANIFEST
    if read(manifest) is not None:
        owned = json.loads(read(manifest))
        if owned.get("identity") != NAME or set(owned.get("files", {})) != {"config.toml", "hooks.json"}:
            raise Conflict("Invalid ownership manifest")
        # Normal trust review may append records. Validate owned fragments rather
        # than requiring unrelated user/trust configuration to remain unchanged.
        uninstall_plan(home)
        for filename, item in owned["files"].items():
            if filename == "config.toml":
                actual = tomlkit.parse(read(home / filename).decode("utf-8"))["mcp_servers"][NAME]
                if (actual["command"] != command[0]
                        or actual["args"] != command[1:] + ["--data-dir", str(data_dir.resolve())]):
                    raise Conflict("Installed observer location differs; review migration first")
        return Plan(home, [], "install")
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
    files = {c.path.name: {"original": c.before.decode("utf-8") if c.before is not None else None,
                           "installed": c.after.decode("utf-8"),
                           "original_hash": digest(c.before), "installed_hash": digest(c.after)} for c in changes}
    record = {"version": 1, "identity": NAME, "files": files}
    changes.append(Change(manifest, None, json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8")))
    return Plan(home, changes, "install")


def uninstall_plan(home):
    """Conservative ownership: stop if changed; never remove ambiguous definitions."""
    home = home.resolve()
    raw = read(home / MANIFEST)
    if raw is None:
        return Plan(home, [], "uninstall")
    record = json.loads(raw)
    if record.get("identity") != NAME or set(record.get("files", {})) != {"config.toml", "hooks.json"}:
        raise Conflict("Invalid ownership manifest")
    changes = []
    for filename, item in record["files"].items():
        current = read(home / filename)
        installed = item["installed"].encode("utf-8")
        original = item["original"].encode("utf-8") if item["original"] is not None else None
        if digest(installed) != item["installed_hash"] or digest(original) != item["original_hash"]:
            raise Conflict("Ownership integrity check failed")
        # Codex trust review changes config.toml. Remove only exact installed text
        # fragments, preserving subsequent user/trust additions outside them.
        matcher = difflib.SequenceMatcher(None, (original or b""), installed, autojunk=False)
        restored = current
        if restored is None:
            raise Conflict("Installed file missing")
        for tag, a, b, c, d in reversed(matcher.get_opcodes()):
            if tag == "equal":
                continue
            old, new = (original or b"")[a:b], installed[c:d]
            if tag != "insert" or not new or restored.count(new) != 1:
                raise Conflict("Owned fragment changed or ambiguous; manual review required")
            restored = restored.replace(new, old, 1)
        if filename.endswith("toml"):
            tomlkit.parse(restored.decode("utf-8"))
        elif restored.strip():
            json.loads(restored)
        if original is None and restored in (b"", b"{}\n"):
            restored = None
        changes.append(Change(home / filename, current, restored))
    changes.append(Change(home / MANIFEST, raw, None))
    return Plan(home, changes, "uninstall")


def apply_plan(plan: Plan):
    """Caller must first show plan.diff and obtain explicit review confirmation."""
    if not plan.changes:
        return None
    plan.home.mkdir(parents=True, exist_ok=True)
    lock = plan.home / ".shion-lifecycle.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise Conflict("Another transaction or interrupted transaction exists") from exc
    os.close(fd)
    backup = plan.home / (".shion-backup-" + uuid.uuid4().hex)
    completed = []
    try:
        for change in plan.changes:
            if read(change.path) != change.before:
                raise Conflict("Configuration changed after preview")
        backup.mkdir(mode=0o700)
        journal = []
        for change in plan.changes:
            if change.before is not None:
                target = backup / change.path.name
                target.write_bytes(change.before)
                if digest(read(target)) != digest(change.before):
                    raise Conflict("Backup hash mismatch")
            journal.append({"file": change.path.name, "before": digest(change.before), "after": digest(change.after)})
        (backup / "journal.json").write_text(json.dumps(journal, indent=2), encoding="utf-8")
        for change in plan.changes:
            if read(change.path) != change.before:
                raise Conflict("Concurrent configuration edit")
            atomic(change.path, change.after)
            completed.append(change)
            if read(change.path) != change.after:
                raise Conflict("Post-write verification failed")
        return backup
    except Exception:
        for change in reversed(completed):
            if read(change.path) != change.after:
                raise Conflict(f"Concurrent edit prevents rollback; retain backup {backup}")
            atomic(change.path, change.before)
        raise
    finally:
        lock.unlink(missing_ok=True)


def inspect(home):
    """Read-only structure summary; never disclose notify arguments or secrets."""
    config = tomlkit.parse((read(home / "config.toml") or b"").decode("utf-8"))
    hooks = json.loads(read(home / "hooks.json") or b"{}")
    state = config.get("hooks", {}).get("state", {})
    return {"home": str(home), "installed": read(home / MANIFEST) is not None,
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
