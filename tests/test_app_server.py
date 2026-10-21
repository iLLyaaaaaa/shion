"""子进程冒烟：真的启动 python -m shion，用 HTTP 发事件，看日志。

用 offscreen 平台（不弹窗）、临时数据目录、随机端口、唯一实例名，
所以不会碰用户正在运行的真桌宠。
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start(tmp_path, port, name):
    data = tmp_path / name
    env = dict(
        os.environ,
        QT_QPA_PLATFORM="offscreen",
        SHION_DATA_DIR=str(data),
        SHION_PORT=str(port),
        SHION_INSTANCE_NAME=f"ShionTest-{os.getpid()}-{name}",
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "shion"], cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return proc, data / "shion.log"


def http(port, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else (b"" if method == "POST" else None)
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method)
    with urllib.request.urlopen(req, timeout=3) as r:
        return json.loads(r.read())


def wait_for(cond, timeout=20.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if cond():
                return True
        except OSError:
            pass
        time.sleep(0.2)
    return False


def log_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def test_real_app_reacts_to_http_event_and_survives_port_conflict(tmp_path):
    port = free_port()
    procs = []
    try:
        p1, log1 = start(tmp_path, port, "a")
        procs.append(p1)
        assert wait_for(lambda: http(port, "GET", "/health") == {"ok": True}), log_text(log1)

        from shion.lines import Lines

        introductions = [line for lang in ("zh", "en", "ja") for line in Lines(lang)._lines["intro"]]
        assert wait_for(lambda: any(line in log_text(log1) for line in introductions)), log_text(log1)

        # 正式启动路径确实加载等级配置并发放每天一次的打开奖励。
        state_path = log1.with_name("state.json")
        assert wait_for(lambda: state_path.exists() and json.loads(state_path.read_text(encoding="utf-8")).get("affection") == 2)
        saved = json.loads(state_path.read_text(encoding="utf-8"))
        assert saved["affection_level"] == 1 and saved["affection_daily"]["open"] == 1

        assert http(port, "POST", "/event", {"type": "working"}) == {"ok": True}
        assert wait_for(lambda: "→ working" in log_text(log1)), log_text(log1)
        http(port, "POST", "/event", {"type": "stop"})
        assert wait_for(lambda: "→ done" in log_text(log1)), log_text(log1)
        assert http(port, "POST", "/feedback/take", {}) == {"text": ""}

        # 第二个实例（实例名不同）抢同一个端口：不崩溃，日志里有提示
        p2, log2 = start(tmp_path, port, "b")
        procs.append(p2)
        assert wait_for(lambda: "HTTP 服务启动失败" in log_text(log2)), log_text(log2)
        time.sleep(1.0)
        assert p2.poll() is None  # 还活着
        assert p1.poll() is None
    finally:
        for p in procs:
            p.kill()
            p.wait(timeout=10)


def test_setup_logging_survives_unwritable_directory(tmp_path):
    import logging

    from shion.app import setup_logging

    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    root = logging.getLogger("shion")
    old = list(root.handlers)
    try:
        setup_logging(blocker / "sub", debug=False)  # 目录建不出来：不能抛
    finally:
        for h in list(root.handlers):
            if h not in old:
                root.removeHandler(h)
