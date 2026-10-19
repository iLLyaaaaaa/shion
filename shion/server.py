"""Shion 的本地 HTTP 服务。

只用标准库，不 import Qt。通过两个回调和外界交互：
``on_event(type, detail)`` 收到事件时调用，``on_take_feedback()`` 取走并清空反馈队列（返回要注入的文字）。
这两个回调都在服务线程里被调用；接到界面时由界面层负责切回 GUI 线程。
"""
from __future__ import annotations

import json
import logging
import math
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional

from .remote import RemoteHub

log = logging.getLogger("shion.server")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 47613
MAX_BODY = 4096
REQUEST_TIMEOUT = 5.0  # 秒：连上不发数据 / 发一半的连接最多占用这么久
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


class _Handler(BaseHTTPRequestHandler):
    server: "_Server"
    protocol_version = "HTTP/1.0"
    timeout = REQUEST_TIMEOUT

    def log_message(self, format, *args):  # noqa: A002
        log.debug("%s - %s", self.address_string(), format % args)

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _allowed(self) -> bool:
        """拒绝来自网页的请求：带 Origin 头（浏览器跨域请求）或 Host 不是本机（DNS 重绑定）。

        Claude Code 的 hook 和 MCP 服务器都是普通 HTTP 客户端，不带 Origin。
        """
        host = self.headers.get("Host")
        if self.headers.get("Origin") is not None or (
            host is not None and host.rsplit(":", 1)[0] not in ALLOWED_HOSTS and host not in ALLOWED_HOSTS
        ):
            self._send(403, {"error": "forbidden"})
            return False
        return True

    def _read_json(self):
        """返回解析后的 JSON；出错时已发送 400 并返回 None。"""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            self._send(400, {"error": "请求体长度不合法或超过 4 KB"})
            return None
        try:
            raw = self.rfile.read(length)
        except OSError:  # 读超时或连接被掐断
            self._send_quietly(408, {"error": "读取请求体超时"})
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._send(400, {"error": "请求体不是合法 JSON"})
            return None

    def _send_quietly(self, status: int, payload: dict) -> None:
        try:
            self._send(status, payload)
        except OSError:
            pass

    def do_GET(self):
        if not self._allowed():
            return
        if self.path == "/health":
            self._send(200, {"ok": True})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._allowed():
            return
        if self.path == "/event":
            self._post_event()
        elif self.path == "/feedback/take":
            self._post_take_feedback()
        elif self.path == "/pause/wait":
            self._post_pause_wait()
        else:
            self._send(404, {"error": "not found"})

    def _post_event(self):
        data = self._read_json()
        if data is None:
            return
        if not isinstance(data, dict):
            self._send(400, {"error": "请求体必须是 JSON 对象"})
            return
        etype, detail = data.get("type"), data.get("detail")
        if not isinstance(etype, str) or not etype:
            self._send(400, {"error": "type 必须是非空字符串"})
            return
        if detail is not None and not isinstance(detail, str):
            self._send(400, {"error": "detail 必须是字符串或 null"})
            return
        if etype == "prompt":
            # 用户在 CC 里说话就解除暂停；在服务线程里直接做，紧接着的工具调用不会再被误挡
            self.server.hub.resume()
        try:
            self.server.on_event(etype, detail)
        except Exception:
            log.exception("on_event 回调出错")
            self._send(500, {"error": "internal error"})
            return
        self._send(200, {"ok": True})

    def _post_take_feedback(self):
        # 读取 body（即使不用），避免连接被意外重置
        if self._read_json() is None:
            return
        try:
            with self.server.feedback_lock:
                text = str(self.server.on_take_feedback())
        except Exception:
            log.exception("on_take_feedback 回调出错")
            self._send(500, {"error": "internal error"})
            return
        self._send(200, {"text": text})

    def _post_pause_wait(self):
        """长轮询：暂停中最多等 wait 秒。只读，不能借此改变暂停状态。"""
        data = self._read_json()
        if data is None:
            return
        wait = data.get("wait", 0) if isinstance(data, dict) else 0
        if isinstance(wait, bool) or not isinstance(wait, (int, float)) or not math.isfinite(wait):
            wait = 0
        self._send(200, {"paused": self.server.hub.wait_while_paused(wait)})


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False  # 端口被占用时要报错，而不是悄悄共用

    def __init__(self, addr, on_event, on_take_feedback, hub):
        super().__init__(addr, _Handler)
        self.on_event = on_event
        self.on_take_feedback = on_take_feedback
        self.hub = hub
        self.feedback_lock = threading.Lock()


class ShionServer:
    def __init__(
        self,
        on_event: Callable[[str, Optional[str]], None],
        on_take_feedback: Callable[[], str],
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        hub: Optional[RemoteHub] = None,
    ):
        self._on_event = on_event
        self._on_take_feedback = on_take_feedback
        self.hub = hub or RemoteHub()
        self._host = host
        self._port = port
        self._httpd: Optional[_Server] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def port(self) -> int:
        return self._httpd.server_address[1] if self._httpd else self._port

    def start(self) -> None:
        """启动服务。端口被占用时抛 OSError。"""
        if self._httpd:
            return
        self._httpd = _Server((self._host, self._port), self._on_event, self._on_take_feedback, self.hub)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="shion-server", daemon=True
        )
        self._thread.start()
        log.info("HTTP 服务已启动：%s:%s", self._host, self.port)

    def stop(self) -> None:
        if not self._httpd:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread:
            self._thread.join(timeout=2)
        self._httpd = self._thread = None
        log.info("HTTP 服务已停止")


def main() -> None:
    """调试入口：用内存里的 PetState 接上服务，不写存档，不需要窗口。"""
    import time
    from datetime import datetime

    from .state import Config, PetState, SaveData

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    pet = PetState(SaveData(), datetime.now(), Config.debug())
    lock = threading.Lock()

    def on_event(etype, detail):
        with lock:
            now = datetime.now()
            reactions = pet.claude_event(etype, detail, now)
            print(f"事件 {etype!r} {detail!r} -> {reactions}  当前：{pet.current(now)}", flush=True)

    def on_take():
        with lock:
            return "\n".join(i["kind"] + ":" + i["text"] for i in pet.take_feedback())

    srv = ShionServer(on_event, on_take)
    srv.start()
    print(f"监听 {DEFAULT_HOST}:{srv.port}，Ctrl+C 退出", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        srv.stop()


if __name__ == "__main__":
    main()
