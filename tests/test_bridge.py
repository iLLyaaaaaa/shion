"""服务线程 → GUI 线程：真 HTTP 服务 + 真网络请求 + 假时钟控制器。"""
import json
import os
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from shion.bridge import ServerBridge
from shion.server import ShionServer
from tests.test_controller import Env


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class Rig:
    def __init__(self, tmp_path, take_timeout=2.0):
        self.env = Env(tmp_path)
        self.threads = []
        orig = self.env.ctl.handle_event

        def recording(etype, detail=None):
            self.threads.append(threading.current_thread())
            orig(etype, detail)

        self.env.ctl.handle_event = recording
        self.bridge = ServerBridge(self.env.ctl, take_timeout=take_timeout)
        self.server = ShionServer(self.bridge.on_event, self.bridge.on_take_praise, port=0)
        self.server.start()
        self.base = f"http://127.0.0.1:{self.server.port}"
        self.pool = ThreadPoolExecutor(max_workers=24)

    def request(self, method, path, body=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
        req = urllib.request.Request(self.base + path, data=data if method == "POST" else None, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def call(self, *a, **kw):
        """在后台线程发请求，主线程继续泵 Qt 事件（桥要靠事件循环才能处理）。"""
        fut = self.pool.submit(self.request, *a, **kw)
        return self.wait(fut)

    def wait(self, fut, timeout=5.0):
        import time

        end = time.monotonic() + timeout
        while not fut.done() and time.monotonic() < end:
            QTest.qWait(5)
        return fut.result(timeout=0.1)

    def pump(self, ms=50):
        QTest.qWait(ms)

    def close(self):
        self.server.stop()
        self.pool.shutdown(wait=False)
        self.env.close()


@pytest.fixture
def rig(qapp, tmp_path):
    r = Rig(tmp_path)
    yield r
    r.close()


def test_health(rig):
    assert rig.call("GET", "/health") == (200, {"ok": True})


def test_event_is_handled_on_the_main_thread_and_changes_pet(rig):
    status, _ = rig.call("POST", "/event", {"type": "working"})
    assert status == 200
    rig.pump()
    assert rig.threads and all(t is threading.main_thread() for t in rig.threads)
    assert rig.env.win.sprite_name == "working"

    rig.call("POST", "/event", {"type": "stop"})
    rig.pump()
    assert rig.env.win.sprite_name == "done"
    assert rig.env.data.stats["claude_tasks"] == 1


def test_all_event_types_over_http(rig):
    for etype, detail in [("session_start", None), ("prompt", None), ("notification", "x"), ("react", "dizzy")]:
        assert rig.call("POST", "/event", {"type": etype, "detail": detail})[0] == 200
    rig.pump()
    assert rig.env.win.sprite_name == "dizzy"
    assert any(t in __import__("shion.lines", fromlist=["Lines"]).Lines()._lines["greeting"] for t in rig.env.said)


def test_concurrent_events_are_all_processed(rig):
    futs = [rig.pool.submit(rig.request, "POST", "/event", {"type": "stop"}) for _ in range(20)]
    assert all(rig.wait(f)[0] == 200 for f in futs)
    rig.pump(100)
    assert rig.env.data.stats["claude_tasks"] == 20
    assert all(t is threading.main_thread() for t in rig.threads)


def test_bad_requests_get_400_and_change_nothing(rig):
    assert rig.call("POST", "/event", raw=b"not json")[0] == 400
    assert rig.call("POST", "/event", {"detail": "x"})[0] == 400
    assert rig.call("POST", "/event", {"type": 5})[0] == 400
    rig.pump()
    assert rig.threads == []
    assert rig.env.win.sprite_name == "idle"
    # 类型是字符串但不认识：服务返回 200，状态机忽略
    assert rig.call("POST", "/event", {"type": "bogus"})[0] == 200
    rig.pump()
    assert rig.env.win.sprite_name == "idle"


def test_praise_take_returns_count_then_zero(rig):
    for _ in range(3):
        rig.env.ctl.praise()
    assert rig.call("POST", "/praise/take", {}) == (200, {"count": 3})
    assert rig.call("POST", "/praise/take", {}) == (200, {"count": 0})


def test_concurrent_praise_take_is_atomic(rig):
    for _ in range(5):
        rig.env.ctl.praise()
    futs = [rig.pool.submit(rig.request, "POST", "/praise/take", {}) for _ in range(20)]
    counts = [rig.wait(f)[1]["count"] for f in futs]
    assert sum(counts) == 5  # 不多领也不漏领
    assert rig.env.data.pending_praise == 0


def test_praise_take_times_out_with_500_when_gui_thread_not_pumping(qapp, tmp_path):
    r = Rig(tmp_path, take_timeout=0.2)
    try:
        fut = r.pool.submit(r.request, "POST", "/praise/take", {})
        fut.result(timeout=5)  # 故意不泵事件循环
        assert fut.result()[0] == 500
    finally:
        r.close()


def test_praise_request_that_timed_out_does_not_lose_the_count(qapp, tmp_path):
    """超时后 GUI 线程才处理到那个请求：不能把计数取走（否则调用方没拿到、计数还丢了）。"""
    r = Rig(tmp_path, take_timeout=0.2)
    try:
        for _ in range(3):
            r.env.ctl.praise()
        fut = r.pool.submit(r.request, "POST", "/praise/take", {})
        fut.result(timeout=5)  # GUI 线程没泵事件 → 超时 500
        assert fut.result()[0] == 500
        r.pump(100)  # 现在才处理排队的请求：已取消，不取数
        assert r.env.data.pending_praise == 3
        r.bridge._take_timeout = 2.0
        assert r.call("POST", "/praise/take", {}) == (200, {"count": 3})
    finally:
        r.close()
