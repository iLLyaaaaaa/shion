"""Independent authenticated loopback inbox. No Claude control routes."""
from __future__ import annotations

import hmac
import json
import queue
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from .events import parse_observation


class ObservationInbox:
    def __init__(self, token: str, capacity=512):
        self.token = token
        self.queue = queue.Queue(capacity)
        self.enabled = True
        self.degraded = threading.Event()
        self.received = 0
        self._epoch, self._count = time.monotonic(), 0

    def submit(self, token, data):
        if not isinstance(token, str) or not hmac.compare_digest(token, self.token):
            return 403
        now = time.monotonic()
        if now - self._epoch >= 1:
            self._epoch, self._count = now, 0
        self._count += 1
        if self._count > 200:
            self.degraded.set()
            return 429
        try:
            event = parse_observation(data)
        except (ValueError, TypeError):
            return 400
        if not self.enabled:
            return 204
        try:
            self.queue.put_nowait((now, event))
        except queue.Full:
            self.degraded.set()
            return 503
        self.received += 1
        return 204

    def drain(self):
        items = []
        for _ in range(self.queue.maxsize):
            try:
                received, event = self.queue.get_nowait()
            except queue.Empty:
                break
            if time.monotonic() - received > 5:
                self.degraded.set()
            else:
                items.append(event)
        return items


class _Handler(BaseHTTPRequestHandler):
    timeout = 0.25

    def log_message(self, *args):
        pass  # No identifiers, credentials or raw request data in logs.

    def do_POST(self):
        status = 400
        if (self.path != "/observe/v1" or self.headers.get("Origin") is not None
                or self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}"):
            status = 403
        elif self.headers.get("Transfer-Encoding") is None:
            try:
                lengths = self.headers.get_all("Content-Length", [])
                length = int(lengths[0]) if len(lengths) == 1 else -1
                if 0 < length <= 2048:
                    token = self.headers.get("Authorization", "").removeprefix("Bearer ")
                    # Authenticate before parsing untrusted JSON.
                    if not hmac.compare_digest(token, self.server.inbox.token):
                        status = 403
                    else:
                        data = json.loads(self.rfile.read(length))
                        status = self.server.inbox.submit(token, data)
                else:
                    status = 413
            except (ValueError, TypeError, OSError):
                status = 400
        try:
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()
        except OSError:
            pass


class ObservationServer:
    def __init__(self, token, port=47614):
        self.inbox = ObservationInbox(token)
        # One worker, bounded listen backlog, bounded body and read timeout.
        self.server = HTTPServer(("127.0.0.1", port), _Handler)
        self.server.inbox = self.inbox
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.1}, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)


def credentials(directory: Path):
    """User-local secret, separate from Claude. Never stored in Codex config."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "chatgpt-observer.json"
    if not path.exists():
        value = {"token": secrets.token_hex(32), "port": 47614, "enabled": True}
        try:
            with path.open("x", encoding="utf-8") as stream:
                json.dump(value, stream)
        except FileExistsError:
            pass
    value = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(value.get("token"), str) or len(value["token"]) != 64
            or type(value.get("port")) is not int or not 1024 <= value["port"] <= 65535
            or type(value.get("enabled")) is not bool):
        raise ValueError("invalid observer configuration")
    return value
