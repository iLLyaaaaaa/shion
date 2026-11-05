"""Claude Desktop stdio observer."""
from __future__ import annotations

import http.client
import threading
import time
import uuid

from shion.loopback import read_link
import json
import os
import sys


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


CLIENT = uuid.uuid4().hex
_sending = threading.Lock()


def notify(event, task=None):
    """A slow token read or unresponsive peer must never hold up Claude."""
    deadline = time.monotonic() + 0.4
    if not _sending.acquire(blocking=False):
        return

    def send_once():
        connection = None
        try:
            token = read_link()
            remaining = deadline - time.monotonic()
            if not token or remaining <= 0:
                return
            port = int(os.environ.get("SHION_PORT") or 47613)
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=min(remaining, 0.12))
            connection.request("POST", "/chat/event", json.dumps(
                {"event": event, "client": CLIENT, "task": task}),
                {"Authorization": "Bearer " + token, "Content-Type": "application/json"})
            connection.getresponse().close()
        except (OSError, ValueError, http.client.HTTPException):
            pass
        finally:
            if connection:
                connection.close()
            _sending.release()

    worker = threading.Thread(target=send_once, daemon=True)
    worker.start()
    worker.join(max(0, deadline - time.monotonic()))


def dispatch(request):
    method = request.get("method")
    params = request.get("params", {})
    if not isinstance(params, dict):
        raise ValueError("invalid params")
    if method == "initialize":
        version = params.get("protocolVersion")
        return {"protocolVersion": version if version in PROTOCOLS else PROTOCOLS[-1],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "shion", "version": "0.1.0"},
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
        task = "".join(c for c in arguments["task"] if c.isprintable()).strip()[:20]
    elif name in ("shion_done", "shion_need_input"):
        if arguments:
            raise ValueError("unexpected arguments")
        task = None
    else:
        raise ValueError("unknown tool")
    notify(name.removeprefix("shion_"), task)
    return {"content": [{"type": "text", "text": "ok"}], "isError": False}


def serve():
    initialized = False

    def online():
        nonlocal initialized
        if not initialized:
            initialized = True
            notify("online")

    try:
        return _serve_loop(online)
    finally:
        if initialized:
            notify("offline")


def _serve_loop(online):
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
                        "error": {"code": -32602, "message": "Invalid request"}}
        try:
            print(json.dumps(response), flush=True)
            if "result" in response and request.get("method") == "initialize":
                online()
        except (BrokenPipeError, OSError):
            return 0


def main(argv=None):
    import argparse
    argparse.ArgumentParser(description="Shion chat MCP").parse_args(argv)
    return serve()
