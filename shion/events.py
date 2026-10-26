"""Strict metadata-only observation contract. Never accepts content fields."""
from __future__ import annotations

from dataclasses import dataclass
import re

EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
          "PermissionRequest", "Stop", "Interrupt")
ID = re.compile(r"[A-Za-z0-9_.:/-]{1,128}\Z")


@dataclass(frozen=True)
class Observation:
    event: str
    session_id: str = ""
    turn_id: str = ""
    tool_use_id: str = ""
    source: str = "global"
    observer: str = ""
    provider: str = "chatgpt"
    namespace: str = "codex-local"

    @property
    def key(self):
        return self.provider, self.namespace, self.session_id, self.turn_id


def parse_observation(data: object) -> Observation:
    allowed = {"event", "session_id", "turn_id", "tool_use_id", "source", "observer"}
    if not isinstance(data, dict) or set(data) - allowed:
        raise ValueError("metadata fields rejected")
    if data.get("event") not in EVENTS:
        raise ValueError("unknown lifecycle event")
    values = dict(data)
    for field in ("session_id", "turn_id", "tool_use_id", "observer"):
        value = values.get(field)
        if value in (None, ""):
            values[field] = ""
        elif not isinstance(value, str) or not ID.fullmatch(value):
            raise ValueError("invalid metadata identifier")
    if values.get("source", "global") not in ("global", "project"):
        raise ValueError("unknown source")
    return Observation(**values)
