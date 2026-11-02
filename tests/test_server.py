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
    assert start_linked(srv, tmp_path) == "ok"
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
        assert start_linked(srv, tmp_path) == "port_busy"
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


# ---- 第二轮：令牌绑定诗音进程、只查最后两层重解析点、写失败要提示 ----
WINDOWS = __import__("os").name == "nt"


def exited_process():
    """起一个子进程、记下进程号和启动时间、等它退出：模拟崩溃后留下旧令牌的诗音。"""
    import subprocess
    import sys
    from shion import winproc
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        created = winproc.process_created(proc.pid)
    finally:
        proc.kill()
        proc.wait(timeout=10)
    return proc.pid, created


@pytest.mark.skipif(not WINDOWS, reason="进程启动时间核对只在 Windows")
def test_read_link_accepts_only_a_token_whose_writer_is_alive(tmp_path):
    import os
    from shion import loopback, winproc
    loopback.write_token(tmp_path, "a" * 64)  # 本进程写的：活着
    assert loopback.read_link(tmp_path) == "a" * 64
    pid, created = exited_process()
    assert created is not None
    loopback.write_token(tmp_path, "b" * 64, pid=pid, created=created)
    assert loopback.read_token(tmp_path) == "b" * 64  # 格式没问题
    assert loopback.read_link(tmp_path) is None  # 但写它的进程已经不在
    me = os.getpid()
    loopback.write_token(tmp_path, "c" * 64, pid=me, created=winproc.process_created(me) + 1)
    assert loopback.read_link(tmp_path) is None  # 进程号活着但启动时间不对（PID 复用）


@pytest.mark.skipif(not WINDOWS, reason="进程启动时间核对只在 Windows")
@pytest.mark.parametrize("record", [{}, {"pid": "1"}, {"pid": 1}, {"pid": 0, "created": 5},
                                    {"pid": True, "created": 5}, {"pid": 1, "created": None}])
def test_read_link_rejects_missing_or_bad_owner_fields(tmp_path, record):
    import json
    from shion import loopback
    loopback.token_path(tmp_path).write_text(json.dumps({"token": "a" * 64, **record}), encoding="utf-8")
    assert loopback.read_link(tmp_path) is None


@pytest.fixture
def junction():
    """建 junction 的工具；测试结束时只解除链接（os.rmdir 不碰目标），不在 build/ 里留下重解析点。"""
    import _winapi
    import os
    made = []

    def make(target, link):
        _winapi.CreateJunction(str(target), str(link))
        made.append(link)

    yield make
    for link in reversed(made):
        try:
            os.rmdir(link)
        except OSError:
            pass


@pytest.mark.skipif(not WINDOWS, reason="junction 只在 Windows")
def test_token_works_under_a_junctioned_parent_directory(tmp_path, junction):
    from shion import loopback
    real = tmp_path / "real-profile"
    real.mkdir()
    junction(real, tmp_path / "moved-profile")
    directory = tmp_path / "moved-profile" / "AppData" / "Shion"  # 上级目录是 junction（搬过家的用户目录）
    loopback.write_token(directory, "d" * 64)
    assert loopback.read_link(directory) == "d" * 64
    loopback.remove_token(directory)
    assert loopback.read_token(directory) is None


@pytest.mark.skipif(not WINDOWS, reason="junction 只在 Windows")
def test_token_refuses_when_the_shion_directory_or_file_is_a_reparse_point(tmp_path, junction):
    from shion import loopback
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    junction(elsewhere, tmp_path / "Shion")
    with pytest.raises(ValueError):
        loopback.write_token(tmp_path / "Shion", "e" * 64)
    assert loopback.read_link(tmp_path / "Shion") is None
    data = tmp_path / "data"
    data.mkdir()
    junction(elsewhere, loopback.token_path(data))  # 令牌文件位置本身是重解析点
    with pytest.raises(ValueError):
        loopback.write_token(data, "e" * 64)
    assert loopback.read_link(data) is None
    assert list(elsewhere.iterdir()) == []  # 没往别处写东西


def test_write_token_leaves_no_temporary_file(tmp_path):
    from shion import loopback
    loopback.write_token(tmp_path, "f" * 64)
    loopback.write_token(tmp_path, "a" * 64)
    assert sorted(p.name for p in tmp_path.iterdir()) == [loopback.TOKEN_FILE]


def test_start_linked_reports_token_failure_and_app_warns(tmp_path, monkeypatch):
    from shion import loopback
    from shion.app import link_warning
    from shion.lines import Lines
    from shion.server import start_linked, stop_linked

    original = loopback.write_token

    def broken(directory, *args, **kwargs):
        if directory == tmp_path / "data":  # 只让正式启动路径写失败（测试的自动登记照常）
            raise OSError("disk says no")
        return original(directory, *args, **kwargs)

    monkeypatch.setattr(loopback, "write_token", broken)
    srv = ShionServer(lambda t, d: None, lambda: "", port=0)
    try:
        assert start_linked(srv, tmp_path / "data") == "token_failed"
        assert loopback.read_token(tmp_path / "data") is None
    finally:
        stop_linked(srv, tmp_path / "data")
    ui = Lines("zh").ui
    assert link_warning("token_failed", ui, 47613) == ui("link_token_failed") != "link_token_failed"
    assert link_warning("port_busy", ui, 47613) == ui("port_busy", port=47613)
    assert link_warning("ok", ui, 47613) is None


def test_start_linked_end_to_end_with_the_real_hook_reader(tmp_path, monkeypatch):
    """只靠 start_linked 写令牌（不走测试的自动登记），hook 真实的 link_token 能读到并连上。"""
    from shion.server import start_linked, stop_linked
    from tests.test_hook import load_hook
    monkeypatch.setenv("SHION_DATA_DIR", str(tmp_path / "elsewhere"))  # 测试自动登记写到别处
    srv = ShionServer(lambda t, d: None, lambda: "", port=0)
    assert start_linked(srv, tmp_path / "data") == "ok"
    try:
        monkeypatch.setenv("SHION_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("SHION_PORT", str(srv.port))
        h = load_hook()
        assert h.link_token() == srv.token
        assert h.request("/health") == {"ok": True}
    finally:
        stop_linked(srv, tmp_path / "data")
    h = load_hook()
    assert h.link_token() is None  # 退出后令牌已删


def test_limits_endpoint_auth_validation_and_control_isolation():
    events=[]
    srv=ShionServer(lambda *args:events.append(args),lambda:'',port=0)
    srv.start()
    try:
        body={'session':'s','five_hour':{'used_percentage':101,'resets_at':2000000000}}
        assert req(srv,'/usage/limits','POST',body,token=None)[0]==403
        assert req(srv,'/usage/limits','POST',{**body,'cwd':'forbidden'})[0]==400
        assert req(srv,'/usage/limits','POST',{**body,'five_hour':{'used_percentage':True,'resets_at':5}})[0]==400
        pending=srv.hub.permissions.open('Bash','synthetic',session='s')
        srv.hub.pause('s')
        assert req(srv,'/usage/limits','POST',body)[0]==200
        assert events==[('usage_limits',None,body)]
        assert srv.hub.permissions.pending()[0].id==pending and srv.hub.is_paused
        assert req(srv,'/event','POST',{'type':'quota_down','session':'s'})[0]==200
        assert srv.hub.permissions.pending()[0].id==pending and srv.hub.is_paused
        assert req(srv,'/event','POST',{'type':'quota_revive','session':'s','detail':'forbidden'})[0]==400
        assert req(srv,'/event','POST',{'type':'usage_limits',**body})[0]==400
        srv.hub.set_link_enabled(False)
        size=len(events)
        assert req(srv,'/usage/limits','POST',body)==(200,{'ok':True,'ignored':True})
        assert len(events)==size
    finally:
        srv.stop()
