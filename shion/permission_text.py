"""Summarize the detail already supplied by the permission hook."""
from __future__ import annotations

import json
import re
from ntpath import basename
from urllib.parse import urlsplit

ACTIONS = {
    "Read": ("read", ("file_path",)),
    "Write": ("write", ("file_path",)),
    "Edit": ("edit", ("file_path",)),
    "NotebookEdit": ("notebook", ("notebook_path", "file_path")),
    "WebFetch": ("fetch", ("url",)),
    "WebSearch": ("search", ("query",)),
    "Task": ("agent", ("description",)),
    "Agent": ("agent", ("description",)),
    "Skill": ("skill", ("skill", "name")),
    "request_directory": ("directory", ("path", "directory", "directory_path")),
}
FILE_ACTIONS = {"read", "write", "edit", "notebook"}
COMMAND_TOOLS = {"Bash", "PowerShell"}
SERVICES = {"claude_in_chrome": "Claude in Chrome"}


def _target(detail: str, keys: tuple[str, ...], *, command: bool) -> str:
    detail = detail.strip()
    if not detail.startswith("{"):
        return detail
    try:
        data = json.loads(detail)
    except (ValueError, RecursionError):
        return detail if command else ""
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


# Recognize only complete read-oriented commands with literal arguments.
_FIND = re.compile(
    r'find[ \t]+(?P<root>[A-Za-z0-9_./:~][A-Za-z0-9_./:~-]*)'
    r'(?:[ \t]+-maxdepth[ \t]+(?P<depth>[0-9]{1,9}))?'
    r'[ \t]+-i?name[ \t]+(?P<quote>["\x27])(?P<pattern>[\w.*?_-]+)(?P=quote)'
    r'(?:[ \t]+2>[ \t]*/dev/null)?'
    r'(?:[ \t]*\|[ \t]*head(?:[ \t]+-n[ \t]+|[ \t]+-)(?P<count>[1-9][0-9]{0,8}))?'
)
_COMMANDS = {
    "git status": "permission_command_git_status",
    "git diff --stat": "permission_command_git_diff_stat",
    "Get-ChildItem": "permission_command_list",
    "ls": "permission_command_list",
}


def _command_and_description(detail: str) -> tuple[str, str]:
    value = _target(detail, ("command",), command=True)
    command, sep, description = value.rpartition("\n# ")
    if not sep or "\n" in description or "\r" in description:
        command, description = value, ""
    return command.strip(), description.strip()


# Keep this conservative. A match adds a warning and never changes the original text.
_COMMAND_PREFIX = r'(?:^|[\s;&|($\x27"])(?:[\w.~/\\:-]+[/\\])?'
_COMMAND_END = r'(?=$|[\s;&|)\x27"])'
_RISKY_COMMAND = re.compile(
    _COMMAND_PREFIX + r'(?:rm|del|Remove-Item|rmdir|rd|erase|format|Format-Volume)(?:\.exe)?' + _COMMAND_END,
    re.IGNORECASE,
)
_RISKY_GIT = re.compile(
    _COMMAND_PREFIX + r'git(?:\.exe)?[ \t]+[^\r\n;&|]*?\b(?:'
    r'push[ \t]+[^\r\n;&|]*?(?<!\S)[\x27"]?(?:--force(?:-with-lease)?|-f)(?=$|[\s=;&|)\x27"])'
    r'|reset[ \t]+[^\r\n;&|]*?(?<!\S)[\x27"]?--hard' + _COMMAND_END + r')',
    re.IGNORECASE,
)
_DOWNLOAD_EXEC = re.compile(
    _COMMAND_PREFIX + r'(?:curl|wget|iwr|irm|Invoke-WebRequest|Invoke-RestMethod)(?:\.exe)?' + _COMMAND_END
    + r'[^\r\n;]*\|[^\r\n;]*?(?:\b(?:sh|bash|zsh|ksh|fish|pwsh|powershell|cmd|iex|Invoke-Expression)'
    r'(?:\.exe)?' + _COMMAND_END + r'|(?:^|[ \t|])&[ \t])',
    re.IGNORECASE,
)


def command_needs_warning(tool: str, detail: str) -> bool:
    if tool not in COMMAND_TOOLS:
        return False
    command, _ = _command_and_description(detail)
    # Fold shell continuation lines for detection only.
    text = re.sub(r"[\\\x60^]\r?\n", "", command or detail)
    return any(pattern.search(text) for pattern in (_RISKY_COMMAND, _RISKY_GIT, _DOWNLOAD_EXEC))


def _command_summary(detail: str, ui) -> str:
    command, description = _command_and_description(detail)
    if command in _COMMANDS:
        return ui(_COMMANDS[command])

    searches = [_FIND.fullmatch(step.strip()) for step in re.split(r"[;\n]", command) if step.strip()]
    if searches and all(searches):
        lines = []
        for search in searches:
            parts = search.groupdict()
            line = ui("permission_command_find", pattern=parts["pattern"], root=parts["root"])
            if parts["depth"] is not None:
                line += ui("permission_command_depth", depth=parts["depth"])
            if parts["count"] is not None:
                line += ui("permission_command_head", count=parts["count"])
            lines.append(line)
        return "\n".join(lines)
    if description:
        return ui("permission_command_description", description=description)
    return ui("permission_command_inspect")


def permission_summary(tool: str, detail: str, ui) -> str:
    prefix, separator, combined = tool.partition("__")
    service, has_tool, action = combined.partition("__")
    if prefix == "mcp" and separator and has_tool and service and action:
        if service.casefold() != "ccd_directory" or action != "request_directory":
            return ui("permission_summary_mcp", service=SERVICES.get(service.casefold(), service), tool=action)
        tool = "request_directory"
    if tool in COMMAND_TOOLS:
        return _command_summary(detail, ui)
    if tool not in ACTIONS:
        return ui("permission_summary_generic")
    kind, keys = ACTIONS[tool]
    value = _target(detail, keys, command=False)
    if kind in FILE_ACTIONS:
        value = basename(value)
    elif kind == "fetch" and value:
        try:
            value = urlsplit(value if "://" in value else "//" + value).hostname or ""
        except ValueError:
            value = ""
    action = ui(f"permission_summary_{kind}")
    return ui("permission_summary_target", action=action, target=value) if value else action
