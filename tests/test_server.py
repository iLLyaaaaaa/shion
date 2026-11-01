import json
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

import pytest

from shion.server import ShionServer
from shion.state import PetState, SaveData


def req(srv, path, method="GET", body=None, raw=None, token="srv"):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    r = urllib.request.Request(f"http://127.0.0.1:{srv.port}{path}", data=data, method=method)
    token = srv.token if token == "srv" else token
    if token is not None:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=3) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


@pytest.fixture
def env():
    events, state = [], {"feedback": ""}

    def take():
        text, state["feedback"] = state["feedback"], ""
        return text

    srv = ShionServer(lambda t, d: events.append((t, d)), take, port=0)
    srv.start()
    yield srv, events, state
    srv.stop()


def test_health(env):
    srv, _, _ = env
    assert req(srv, "/health") == (200, {"ok": True})


def test_event_forwarded(env):
    srv, events, _ = env
    assert req(srv, "/event", "POST", {"type": "working"})[0] == 200
    assert req(srv, "/event", "POST", {"type": "react", "detail": "开心"})[0] == 200
    assert req(srv, "/event", "POST", {"type": "stop", "detail": None})[0] == 200
    assert events == [("working", None), ("react", "开心"), ("stop", None)]


@pytest.mark.parametrize(
    "raw",
    [
        b"not json",
        b"[1, 2]",
        b"{}",
        b'{"type": 5}',
        b'{"type": ""}',
        b'{"type": "stop", "detail": 3}',
        b'{"type": "x", "detail": "' + b"a" * 5000 + b'"}',
    ],
)
def test_event_bad_request(env, raw):
    srv, events, _ = env
    assert req(srv, "/event", "POST", raw=raw)[0] == 400
    assert events == []


def test_404(env):
    srv, _, _ = env
    assert req(srv, "/nope")[0] == 404
    assert req(srv, "/event")[0] == 404  # GET /event
    assert req(srv, "/health", "POST", {})[0] == 404


def test_take_feedback(env):
    srv, _, state = env
    state["feedback"] = "你好"
    assert req(srv, "/feedback/take", "POST", {}) == (200, {"text": "你好"})
    assert req(srv, "/feedback/take", "POST", {}) == (200, {"text": ""})
    # 空请求体也行
    assert req(srv, "/feedback/take", "POST", raw=b"")[0] in (200, 400)
    # 旧的夸奖接口已经取消
    assert req(srv, "/praise/take", "POST", {})[0] == 404


def test_take_feedback_serialized():
    active, overlaps = [0], [0]

    def take():
        active[0] += 1
        if active[0] > 1:
            overlaps[0] += 1
        time.sleep(0.01)
        active[0] -= 1
        return ""

    srv = ShionServer(lambda t, d: None, take, port=0)
    srv.start()
    try:
        ts = [threading.Thread(target=req, args=(srv, "/feedback/take", "POST", {})) for _ in range(20)]
        [t.start() for t in ts]
        [t.join() for t in ts]
    finally:
        srv.stop()
    assert overlaps[0] == 0


def test_callback_exception_gives_500():
    def boom(t, d):
        raise RuntimeError("x")

    srv = ShionServer(boom, lambda: 1 / 0, port=0)
    srv.start()
    try:
        assert req(srv, "/event", "POST", {"type": "stop"})[0] == 500
        assert req(srv, "/feedback/take", "POST", {})[0] == 500
        assert req(srv, "/health")[0] == 200
    finally:
        srv.stop()


def test_with_real_petstate():
    now = datetime(2026, 1, 1, 12, 0)
    pet = PetState(SaveData(), now)
    pet.feedback_good(now)
    pet.feedback_bad("x", now)
    srv = ShionServer(
        lambda t, d: pet.claude_event(t, d, now), lambda: str(len(pet.take_feedback(now))), port=0
    )
    srv.start()
    try:
        assert req(srv, "/feedback/take", "POST", {})[1]["text"] == "2"
        assert req(srv, "/feedback/take", "POST", {})[1]["text"] == "0"
        assert req(srv, "/event", "POST", {"type": "stop"})[0] == 200
        assert req(srv, "/event", "POST", {"type": "bogus"})[0] == 200  # 未知类型由状态机忽略
        assert pet.current(now) == "done"
    finally:
        srv.stop()


def test_stop_and_port_in_use():
    a = ShionServer(lambda t, d: None, lambda: 0, port=0)
    a.start()
    port = a.port
    b = ShionServer(lambda t, d: None, lambda: 0, port=port)
    with pytest.raises(OSError):
        b.start()
    a.stop()
    a.stop()  # 重复 stop 不报错
    with pytest.raises(OSError):
        urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)


# ---- 审查修复：网页请求 / 慢连接 ----
def raw_request(srv, headers: dict, path="/event", body=b'{"type": "stop"}', method="POST"):
    import http.client

    c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=3)
    try:
        c.putrequest(method, path, skip_host=True)
        headers = {"Authorization": "Bearer " + srv.token, **headers}
        for k, v in headers.items():
            if v is not None:
                c.putheader(k, v)
        c.putheader("Content-Length", str(len(body)))
        c.endheaders(body)
        r = c.getresponse()
        return r.status, r.read()
    finally:
        c.close()


def test_origin_header_is_rejected_and_callback_not_called(env):
    srv, events, _ = env
    status, _ = raw_request(srv, {"Host": f"127.0.0.1:{srv.port}", "Origin": "https://evil.example"})
    assert status == 403
    status, _ = raw_request(srv, {"Host": f"127.0.0.1:{srv.port}", "Origin": "null"}, "/health", b"", "GET")
    assert status == 403
    assert events == []


def test_foreign_host_header_is_rejected(env):
    srv, events, _ = env
    assert raw_request(srv, {"Host": "evil.example"})[0] == 403
    assert raw_request(srv, {"Host": f"evil.example:{srv.port}"})[0] == 403
    assert events == []


def test_localhost_and_127_hosts_are_accepted(env):
    srv, events, _ = env
    assert raw_request(srv, {"Host": f"127.0.0.1:{srv.port}"})[0] == 200
    assert raw_request(srv, {"Host": f"localhost:{srv.port}"})[0] == 200
    assert len(events) == 2


CRLF = bytes([13, 10])


def test_incomplete_body_times_out_instead_of_hanging(monkeypatch):
    import socket

    from shion import server as server_mod

    monkeypatch.setattr(server_mod._Handler, "timeout", 0.3)
    srv = ShionServer(lambda t, d: None, lambda: 0, port=0)
    srv.start()
    try:
        s = socket.create_connection(("127.0.0.1", srv.port), timeout=3)
        s.sendall(b"POST /event HTTP/1.0" + CRLF + b"Host: 127.0.0.1" + CRLF
                  + b"Authorization: Bearer " + srv.token.encode() + CRLF
                  + b"Content-Length: 100" + CRLF + CRLF + b'{"ty')
        t0 = time.monotonic()
        data = s.recv(4096)  # 服务端超时后回 408 并关闭连接
        assert time.monotonic() - t0 < 2.0
        assert b"408" in data or data == b""
        s.close()
        assert req(srv, "/health") == (200, {"ok": True})  # 服务仍然可用
    finally:
        srv.stop()


# ---- 令牌：只有读得到数据目录令牌的 hook 才能和诗音对话 ----
ROUTES = [("GET", "/health"), ("POST", "/event"), ("POST", "/feedback/take"), ("POST", "/pause/wait"),
          ("POST", "/permission/open"), ("POST", "/permission/wait"), ("POST", "/permission/withdraw"),
          ("POST", "/permission/settle")]


@pytest.mark.parametrize("method,path", ROUTES)
@pytest.mark.parametrize("token", [None, "", "0" * 64, "Bearer", "x" * 300, "é" * 64])
def test_every_route_rejects_missing_or_wrong_token(env, method, path, token):
    srv, events, _ = env
    body = {"type": "prompt", "session": "s1"} if method == "POST" else None
    status, payload = req(srv, path, method, body, token=token)
    assert (status, payload) == (403, {"error": "forbidden"})
    assert events == []


def test_wrong_token_neither_forwards_events_nor_takes_feedback(env):
    srv, events, state = env
    state["feedback"] = "只给真的 hook"
    for token in (None, "f" * 64):
        assert req(srv, "/event", "POST", {"type": "prompt"}, token=token)[0] == 403
        assert req(srv, "/feedback/take", "POST", {}, token=token)[0] == 403
    assert events == [] and state["feedback"] == "只给真的 hook"
    assert req(srv, "/feedback/take", "POST", {}) == (200, {"text": "只给真的 hook"})


def test_wrong_token_cannot_release_a_pause():
    from shion.remote import RemoteHub
    hub = RemoteHub()
    srv = ShionServer(lambda t, d, m=None: None, lambda s=None: "", port=0, hub=hub)
    srv.start()
    try:
        hub.pause()
        assert req(srv, "/event", "POST", {"type": "prompt"}, token="a" * 64)[0] == 403
        assert hub.is_paused
        assert req(srv, "/event", "POST", {"type": "prompt"})[0] == 200
        assert not hub.is_paused
    finally:
        srv.stop()


def test_server_token_is_random_and_validated():
    a = ShionServer(lambda t, d: None, lambda: "", port=0)
    b = ShionServer(lambda t, d: None, lambda: "", port=0)
    assert a.token != b.token and len(a.token) == 64
    with pytest.raises(ValueError):
        ShionServer(lambda t, d: None, lambda: "", port=0, token="short")


@pytest.mark.skipif(__import__("os").name != "nt", reason="SO_EXCLUSIVEADDRUSE 只在 Windows")
def test_bound_port_cannot_be_rebound_even_with_reuseaddr(env):
    import socket
    srv, _, _ = env
    s = socket.socket()
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        with pytest.raises(OSError):
            s.bind(("127.0.0.1", srv.port))
    finally:
        s.close()


@pytest.mark.skipif(__import__("os").name != "nt", reason="SO_EXCLUSIVEADDRUSE 只在 Windows")
def test_observer_port_cannot_be_rebound_even_with_reuseaddr():
    import socket
    from shion.observer import ObservationServer
    obs = ObservationServer("a" * 64, port=0)
    obs.start()
    try:
        port = obs.server.server_address[1]
        assert obs.server.server_port == port
        s = socket.socket()
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            with pytest.raises(OSError):
                s.bind(("127.0.0.1", port))
        finally:
            s.close()
    finally:
        obs.stop()


def test_start_linked_writes_token_only_after_bind_and_stop_removes_it(tmp_path):
    from shion import loopback
    from shion.server import start_linked, stop_linked
    loopback.write_token(tmp_path, "c" * 64)  # 上次崩溃留下的旧令牌
    srv = ShionServer(lambda t, d: None, lambda: "", port=0)
    assert start_linked(srv, tmp_path) is True
    try:
        assert loopback.read_token(tmp_path) == srv.token
        assert req(srv, "/health") == (200, {"ok": True})
    finally:
        stop_linked(srv, tmp_path)
    assert loopback.read_token(tmp_path) is None
    assert not loopback.token_path(tmp_path).exists()


def test_start_linked_on_busy_port_leaves_no_token(tmp_path):
    import socket
    from shion import loopback
    from shion.server import start_linked
    squatter = socket.socket()
    squatter.bind(("127.0.0.1", 0))
    squatter.listen(1)
    try:
        loopback.write_token(tmp_path, "d" * 64)  # 旧令牌也必须被删掉
        srv = ShionServer(lambda t, d: None, lambda: "", port=squatter.getsockname()[1])
        assert start_linked(srv, tmp_path) is False
        assert loopback.read_token(tmp_path) is None
    finally:
        squatter.close()


def test_read_token_rejects_bad_content(tmp_path):
    from shion import loopback
    path = loopback.token_path(tmp_path)
    for content in ("", "not json", "[]", '{"token": 5}', '{"token": "abc"}', '{"token": "' + "G" * 64 + '"}'):
        path.write_text(content, encoding="utf-8")
        assert loopback.read_token(tmp_path) is None
    assert loopback.read_token(tmp_path / "missing") is None
