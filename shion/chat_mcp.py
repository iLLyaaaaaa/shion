"""Step 0 chat MCP probe: stdio to a local JSONL file, with no pet connection."""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import sys

# Keep this probe independent of the lifecycle observer and its network imports.
PROTOCOLS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
INSTRUCTIONS = (
    "Shion is the user's desktop pet. It shows whether Claude is busy. For tasks that use tools or take a while, "
    "call shion_working before starting and shion_done when finished. Skip both for quick replies. "
    "There is no need to mention these calls to the user. Never pass conversation content."
)
TOOLS = [
    {"name": "shion_working", "description": (
        "Call BEFORE starting a task that uses tools (web search, files, code, artifacts) or is expected to take "
        "more than about 30 seconds. Do not call for quick answers. task: a 2-6 word label in the user's "
        "language, with no personal or sensitive details."),
     "inputSchema": {"type": "object", "additionalProperties": False,
                     "properties": {"task": {"type": "string", "maxLength": 20}}, "required": ["task"]}},
    {"name": "shion_done", "description": (
        "Call once when the task announced with shion_working is finished, failed or abandoned, "
        "as the last step before your final reply."),
     "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}}},
    {"name": "shion_need_input", "description": (
        "Call when you stop mid-task to ask the user a question or wait for their confirmation."),
     "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}}},
]


def dispatch(request):
    method = request.get("method")
    params = request.get("params", {})
    if not isinstance(params, dict):
        raise ValueError("invalid params")
    if method == "initialize":
        version = params.get("protocolVersion")
        return {"protocolVersion": version if version in PROTOCOLS else PROTOCOLS[-1],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "shion-probe", "version": "0.1.0"},
                "instructions": INSTRUCTIONS}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method != "tools/call":
        raise LookupError("unknown method")
    name = params.get("name")
    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        raise ValueError("invalid arguments")
    if name == "shion_working":
        if set(arguments) != {"task"} or not isinstance(arguments["task"], str):
            raise ValueError("invalid task")
        # Deliberately retain even overlong labels for this experiment.
        task = arguments["task"]
    elif name in ("shion_done", "shion_need_input"):
        if arguments:
            raise ValueError("unexpected arguments")
        task = None
    else:
        raise ValueError("unknown tool")
    directory = Path(os.environ["APPDATA"]) / "Shion"
    directory.mkdir(parents=True, exist_ok=True)
    record = {"tool": name, "time": datetime.now().astimezone().isoformat(), "task": task}
    with (directory / "chat-mcp-probe.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(record, ensure_ascii=True) + "\n")
    return {"content": [{"type": "text", "text": "ok"}], "isError": False}


def serve():
    while True:
        raw = sys.stdin.buffer.readline(8193)
        if not raw:
            return 0
        if len(raw) > 8192 or not raw.endswith(b"\n"):
            return 0
        request = None
        try:
            request = json.loads(raw)
            if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
                raise ValueError("invalid request")
            if "id" not in request:
                continue
            result = dispatch(request)
            response = {"jsonrpc": "2.0", "id": request["id"], "result": result}
        except (ValueError, TypeError, LookupError, RecursionError):
            response = {"jsonrpc": "2.0", "id": request.get("id") if isinstance(request, dict) else None,
                        "error": {"code": -32602, "message": "Invalid probe request"}}
        except OSError:
            response = {"jsonrpc": "2.0", "id": request["id"],
                        "result": {"content": [{"type": "text", "text": "Probe write failed"}], "isError": True}}
        try:
            print(json.dumps(response), flush=True)
        except (BrokenPipeError, OSError):
            return 0


def main(argv=None):
    import argparse
    argparse.ArgumentParser(description="Shion chat MCP probe").parse_args(argv)
    return serve()
