"""Step 0 only: read transcript metadata; write a fixed, aggregate-only report.

No transcript text, source filenames, identifiers or errors are emitted. The
CLI has no output-path option and never writes inside the Claude config dir.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "build" / "probe-usage.txt"
MAX_LINE = 1024 * 1024
TOKENS = ("input_tokens", "output_tokens", "cache_creation_input_tokens",
          "cache_read_input_tokens")
CLIENT_FIELDS = ("entrypoint", "client", "clientType", "client_type", "source")
# Unknown strings are counted, never echoed: they may be private labels.
CLIENT_VALUES = frozenset(("cli", "desktop", "vscode", "web", "api", "sdk",
    "sdk-cli", "sdk-ts", "sdk-py", "claude-desktop", "claude-vscode",
    "claude-code", "claude-code-desktop", "local", "remote", "external"))
MODEL = re.compile(r"claude-(?:(?:opus|sonnet|haiku)(?:-\d+)+|"
                   r"\d+(?:-\d+)*-(?:opus|sonnet|haiku)(?:-\d+)*)(?:-thinking)?\Z")


def metadata_only(pairs: list[tuple[str, object]]) -> dict:
    """Discard unrelated JSON members immediately, without inspecting them."""
    allowed = {"type", "timestamp", "message", "id", "requestId", "model",
               "usage", *TOKENS, *CLIENT_FIELDS}
    return {key: value for key, value in pairs if key in allowed}


def bounded_lines(stream):
    """Drain oversized records in bounded chunks, never parse their suffix."""
    while chunk := stream.readline(MAX_LINE + 1):
        if len(chunk) > MAX_LINE:
            while not chunk.endswith(b"\n"):
                chunk = stream.readline(MAX_LINE + 1)
                if not chunk:
                    break
            yield None
        else:
            yield chunk


def local_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # An ambiguous timestamp must not silently acquire the machine timezone.
        if stamp.tzinfo is None:
            return None
        return stamp.astimezone().date()
    except (ValueError, OverflowError, OSError):
        return None


def safe_model(value: object) -> str:
    if isinstance(value, str) and len(value) <= 100 and MODEL.fullmatch(value):
        return value
    return "<other-model>"


def safe_client(value: object) -> str:
    if value is None:
        return "<null>"
    if isinstance(value, str) and value in CLIENT_VALUES:
        return value
    return "<other>"


def scan(projects: Path, today: date | None = None) -> dict:
    """Read-only full scan. Duplicates use the first valid row encountered.

    Diagnostics stay in memory: only the spec's aggregate fields are returned.
    Missing identifiers, invalid dates/counts and malformed records are skipped.
    An unreadable file aborts rather than presenting partial totals as complete.
    """
    today = today or datetime.now().astimezone().date()
    days = {str(today - timedelta(days=offset)): [0, 0, 0, 0]
            for offset in reversed(range(7))}
    files = usage_lines = before = 0
    seen = set()
    models = set()
    first = last = None
    clients = {field: Counter() for field in CLIENT_FIELDS}
    diagnostics = Counter()
    markers = (b'"usage"', *(('"' + field + '"').encode() for field in CLIENT_FIELDS))
    for path in sorted(projects.rglob("*.jsonl")) if projects.exists() else ():
        if not path.is_file() or path.is_symlink():
            continue
        files += 1
        with path.open("rb") as stream:
            for line in bounded_lines(stream):
                if line is None:
                    diagnostics["oversized"] += 1
                    continue
                if not any(marker in line for marker in markers):
                    continue
                try:
                    row = json.loads(line, object_pairs_hook=metadata_only)
                except (ValueError, UnicodeError, RecursionError):
                    diagnostics["malformed"] += 1
                    continue
                if not isinstance(row, dict):
                    continue
                for field in CLIENT_FIELDS:
                    if field in row:
                        clients[field][safe_client(row[field])] += 1
                if row.get("type") != "assistant":
                    continue
                message = row.get("message")
                if not isinstance(message, dict) or not isinstance(message.get("usage"), dict):
                    continue
                usage_lines += 1
                ids = (message.get("id"), row.get("requestId"))
                if any(value is not None and (not isinstance(value, str) or not value)
                       for value in ids) or not any(ids):
                    diagnostics["identifier"] += 1
                    continue
                day = local_date(row.get("timestamp"))
                counts = tuple(message["usage"].get(key, 0) for key in TOKENS)
                if day is None or any(type(value) is not int or value < 0 for value in counts):
                    diagnostics["invalid_usage"] += 1
                    continue
                before += 1
                if ids in seen:
                    continue
                seen.add(ids)
                models.add(safe_model(message.get("model")))
                first = day if first is None else min(first, day)
                last = day if last is None else max(last, day)
                if str(day) in days:
                    days[str(day)] = [a + b for a, b in zip(days[str(day)], counts)]
    return {
        "file_count": files,
        "assistant_usage_lines": usage_lines,
        "before_dedup": before,
        "after_dedup": len(seen),
        "last_7_days": {day: dict(zip(TOKENS, counts)) for day, counts in days.items()},
        "models": sorted(models),
        "earliest_date": str(first) if first else None,
        "latest_date": str(last) if last else None,
        "client_fields": {field: dict(sorted(counts.items()))
                          for field, counts in clients.items() if counts},
    }


def main() -> int:
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    try:
        report = scan(config / "projects")
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, RecursionError):
        # Never print exceptions: they can contain source paths or transcript data.
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
