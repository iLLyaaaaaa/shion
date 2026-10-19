import json
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

import pytest

from shion.server import ShionServer
from shion.state import PetState, SaveData


def req(srv, path, method="GET", body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    r = urllib.request.Request(f"http://127.0.0.1:{srv.port}{path}", data=data, method=method)
    try:
        with urllib.request.urlopen(r, timeout=3) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


@pytest.fixture
def env():
    events, state = [], {"praise": 0}

    def take():
        n, state["praise"] = state["praise"], 0
        return n

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


def test_take_praise(env):
    srv, _, state = env
    state["praise"] = 3
    assert req(srv, "/praise/take", "POST", {}) == (200, {"count": 3})
    assert req(srv, "/praise/take", "POST", {}) == (200, {"count": 0})
    # 空请求体也行
    assert req(srv, "/praise/take", "POST", raw=b"")[0] in (200, 400)


def test_take_praise_serialized():
    active, overlaps = [0], [0]

    def take():
        active[0] += 1
        if active[0] > 1:
            overlaps[0] += 1
        time.sleep(0.01)
        active[0] -= 1
        return 1

    srv = ShionServer(lambda t, d: None, take, port=0)
    srv.start()
    try:
        ts = [threading.Thread(target=req, args=(srv, "/praise/take", "POST", {})) for _ in range(20)]
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
        assert req(srv, "/praise/take", "POST", {})[0] == 500
        assert req(srv, "/health")[0] == 200
    finally:
        srv.stop()


def test_with_real_petstate():
    now = datetime(2026, 1, 1, 12, 0)
    pet = PetState(SaveData(), now)
    pet.praise_claude(now)
    pet.praise_claude(now)
    srv = ShionServer(lambda t, d: pet.claude_event(t, d, now), pet.take_praise, port=0)
    srv.start()
    try:
        assert req(srv, "/praise/take", "POST", {})[1]["count"] == 2
        assert req(srv, "/praise/take", "POST", {})[1]["count"] == 0
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
