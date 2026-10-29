"""Stdio MCP metadata sink. Always returns a neutral hook result, even offline."""
from __future__ import annotations

import http.client
import json
import sys
import uuid
import threading
from pathlib import Path

from .events import EVENTS, parse_observation
from .observer_files import read_private

PROTOCOLS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
HEARTBEAT_INTERVAL = 2.0
SCHEMA = {"type": "object", "additionalProperties": False,
          "properties": {"event": {"type": "string", "enum": list(EVENTS)},
                         **{k: {"type": ["string", "null"], "maxLength": 128}
                            for k in ("session_id", "turn_id", "tool_use_id")},
                         "source": {"type": "string", "enum": ["global", "project"]}},
          "required": ["event", "source"]}


def forward(data, directory: Path, path="/observe/v1"):
    # Read only our small credential file; never client config, history, or tool data.
    try:
        config = json.loads(read_private(directory / "chatgpt-observer.json"))
        if (not isinstance(config, dict) or config.get("enabled") is not True
                or type(config.get("port")) is not int or not 1024 <= config["port"] <= 65535
                or not isinstance(config.get("token"), str) or len(config["token"]) != 64
                or any(c not in "0123456789abcdef" for c in config["token"])):
            return
        connection = http.client.HTTPConnection("127.0.0.1", config["port"], timeout=0.15)
        try:
            connection.request("POST", path, json.dumps(data),
                               {"Authorization": "Bearer " + config["token"],
                                "Content-Type": "application/json"})
            connection.getresponse().close()
        finally:
            connection.close()
    except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException, RecursionError):
        pass


class HeartbeatSender:
    """One daemon per stdio Observer; no stdout and no dependence on Hook traffic."""
    def __init__(self, directory, observer, interval=HEARTBEAT_INTERVAL):
        self.directory, self.observer, self.interval = directory, observer, interval
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True, name="observer-heartbeat")

    def _run(self):
        while not self.stopped.is_set():
            forward({"observer": self.observer}, self.directory, "/observe/heartbeat/v1")
            self.stopped.wait(self.interval)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stopped.set()
        self.thread.join(timeout=0.5)


def dispatch(request, directory, observer, *, leased=False):
    method = request.get("method")
    params = request.get("params", {})
    if not isinstance(params, dict):
        raise ValueError("invalid params")
    if method == "initialize":
        version = params.get("protocolVersion")
        return {"protocolVersion": version if version in PROTOCOLS else PROTOCOLS[-1],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "shion_lifecycle_v1", "version": "1.0.0"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [{"name": "observe_lifecycle", "description": "Observe lifecycle metadata only",
                           "inputSchema": SCHEMA,
                           "annotations": {"readOnlyHint": True, "destructiveHint": False,
                                           "openWorldHint": False}}]}
    if method == "tools/call":
        if params.get("name") != "observe_lifecycle":
            raise ValueError("unknown tool")
        data = params.get("arguments")
        event = parse_observation(data)
        if "observer" in data or "leased" in data:
            raise ValueError("observer and lease capability are assigned by the transport")
        payload = {k: getattr(event, k) for k in ("event", "session_id", "turn_id", "tool_use_id", "source")}
        payload["observer"] = observer
        if leased:
            payload["leased"] = True
        forward(payload, directory)
        return {"content": [{"type": "text", "text": "{}"}], "isError": False}
    raise LookupError("method not found")


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    observer = uuid.uuid4().hex
    with HeartbeatSender(args.data_dir, observer):
        return serve(args.data_dir, observer)


def serve(directory, observer):
    while True:
        raw = sys.stdin.buffer.readline(8193)
        if not raw:
            break
        if len(raw) > 8192 or not raw.endswith(b"\n"):
            # Stop malformed streams rather than retaining unbounded content.
            return 0
        request = None
        try:
            request = json.loads(raw)
            if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
                raise ValueError("invalid request")
            if "id" not in request:
                continue
            result = dispatch(request, directory, observer, leased=True)
            response = {"jsonrpc": "2.0", "id": request["id"], "result": result}
        except (ValueError, TypeError, LookupError, RecursionError):
            response = {"jsonrpc": "2.0", "id": request.get("id") if isinstance(request, dict) else None,
                        "error": {"code": -32602, "message": "Invalid metadata request"}}
        try:
            print(json.dumps(response), flush=True)
        except (BrokenPipeError, OSError):
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
