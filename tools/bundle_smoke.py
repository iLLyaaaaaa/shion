"""用标准库测试复制后的 exe；不导入源码中的业务模块，不运行 Claude。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time
import urllib.request
import uuid


def isolated_environment(home: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(("PYTHON", "PYINSTALLER", "_PYI", "QT_", "PYSIDE", "SHION_"))
           and key.upper() not in ("VIRTUAL_ENV", "CONDA_PREFIX")}
    home.mkdir()
    drive, tail = os.path.splitdrive(str(home))
    windows = os.environ.get("SystemRoot", r"C:\Windows")
    env.update(HOME=str(home), USERPROFILE=str(home), HOMEDRIVE=drive, HOMEPATH=tail,
               APPDATA=str(home / "AppData" / "Roaming"),
               PATH=os.pathsep.join((str(Path(windows) / "System32"), windows)),
               QT_QPA_PLATFORM="offscreen", SHION_INSTANCE_NAME=f"ShionBundle-{uuid.uuid4().hex}")
    return env


def wait_for(predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except (OSError, ValueError):
            pass
        time.sleep(0.1)
    raise RuntimeError("等待复制后的程序响应超时")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def http(port, path, data=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 data=None if data is None else json.dumps(data).encode(),
                                 headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=2) as response:
        return json.loads(response.read())


def manifest(directory: Path) -> dict[str, str]:
    return {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.rglob("*") if p.is_file()}


def own_processes(exe: Path, terminate=False) -> list[int]:
    """只查询/结束本次唯一临时 exe 路径对应的进程，句柄查询与结束之间不重新按 PID 打开。"""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                 wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    pids = (wintypes.DWORD * 32768)()
    used = wintypes.DWORD()
    if not psapi.EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(used)):
        raise ctypes.WinError(ctypes.get_last_error())
    result = []
    for pid in pids[:used.value // ctypes.sizeof(wintypes.DWORD)]:
        rights = 0x1000 | (0x0001 | 0x100000 if terminate else 0)
        handle = kernel.OpenProcess(rights, False, pid)
        if not handle:
            continue
        try:
            size = wintypes.DWORD(32768)
            path = ctypes.create_unicode_buffer(size.value)
            if kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)) and Path(path.value) == exe:
                result.append(pid)
                if terminate:
                    if not kernel.TerminateProcess(handle, 0):
                        raise ctypes.WinError(ctypes.get_last_error())
                    kernel.WaitForSingleObject(handle, 5000)
        finally:
            kernel.CloseHandle(handle)
    return result


class MockHooks:
    def __init__(self):
        self.events = []
        self.gate = {"paused": False}
        self.decision = "allow"
        self.feedback = ""
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.respond({"ok": True})

            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                if self.path == "/event":
                    owner.events.append(data)
                    answer = {"ok": True}
                elif self.path == "/pause/wait":
                    answer = owner.gate
                elif self.path == "/feedback/take":
                    answer = {"text": owner.feedback}
                elif self.path == "/permission/open":
                    answer = {"id": "bundle-request"}
                elif self.path == "/permission/wait":
                    answer = {"id": "bundle-request", "status": owner.decision}
                else:
                    answer = {"ok": True}
                self.respond(answer)

            def respond(self, answer):
                content = json.dumps(answer).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


def check_bundle(bundle: Path, evidence: Path) -> dict:
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "subprocess.log").write_bytes(b"")
    for previous in evidence.glob("*.png"):
        previous.unlink()
    report = {"checks": [], "timings_seconds": {}, "snapshots": []}

    def require(condition, name):
        if not condition:
            raise AssertionError(name)
        report["checks"].append(name)

    with tempfile.TemporaryDirectory(prefix="Shion-bundle-") as temporary:
        base = Path(temporary)
        relocated = base / "诗音 with spaces" / "Shion"
        shutil.copytree(bundle, relocated)
        exe = relocated / "Shion.exe"
        cwd = base / "unrelated working directory"
        cwd.mkdir()
        env = isolated_environment(base / "home")
        before = manifest(relocated)

        def run(args, payload=None, expected=0, timeout=30, environment=None):
            started = time.monotonic()
            result = subprocess.run([str(exe), *args], cwd=cwd, env=environment or env,
                                    input=json.dumps(payload or {}, ensure_ascii=False).encode("utf-8"),
                                    capture_output=True, timeout=timeout)
            label = " ".join(args[:2])
            report["timings_seconds"][label] = round(time.monotonic() - started, 3)
            with (evidence / "subprocess.log").open("ab") as log:
                log.write((label + f" -> {result.returncode}\n").encode("utf-8") + result.stdout + result.stderr + b"\n")
            require(result.returncode == expected,
                    f"exit {label}: {result.returncode}; {result.stderr.decode('utf-8', 'replace')}")
            return result

        try:
            require(not (relocated / ".venv").exists(), "copy-without-venv")
            content = exe.read_bytes()
            pe = struct.unpack_from("<I", content, 0x3C)[0]
            require(struct.unpack_from("<H", content, pe + 24 + 68)[0] == 2, "windows-gui-subsystem")
            connection = json.loads(run(["--self-check-connection", env["HOME"]]).stdout)
            require(connection["ok"], "frozen-HookConnection")
            require(all(not str(p).lower().startswith(str(Path(__file__).resolve().parent.parent).lower())
                        for p in connection["sys_path"]), "no-source-in-frozen-sys-path")
            report["connection"] = connection
            # 护栏拒绝不匹配的 HOME，且不尝试读取用户配置。
            run(["--self-check-connection", str(base)], expected=1)

            # 原生平台负责字体回退与实际发布画面；另保留一张 offscreen 验证平台插件。
            native_env = {**env, "QT_QPA_PLATFORM": "windows"}
            snapshots = [
                ("offscreen-idle", []), ("idle", []),
                ("working", ["--state", "working", "--nod", "--at", "0.2"]),
                ("bed", ["--state", "bed", "--at", "1"]),
                ("desk", ["--state", "desk", "--desk-blink", "double", "--at", "0.2"]),
                ("snacks", ["--panel", "snacks", "--lang", "ja"]),
                *[(f"connection-{lang}", ["--panel", "connection", "--with-pet", "--lang", lang])
                  for lang in ("zh", "en", "ja")],
            ]
            for name, args in snapshots:
                output = base / f"{name}.png"
                run(["--snapshot", str(output), *args],
                    environment=env if name == "offscreen-idle" else native_env)
                png = output.read_bytes()
                require(png[:8] == b"\x89PNG\r\n\x1a\n" and all(
                    n > 20 for n in struct.unpack_from(">II", png, 16)), f"snapshot-{name}")
                shutil.copy2(output, evidence / output.name)
                report["snapshots"].append(output.name)

            with MockHooks() as mock:
                env["SHION_PORT"] = str(mock.server.server_port)
                payload = {"session_id": "临时会话", "tool_name": "Read", "tool_input": {"file_path": "测试.txt"},
                           "tool_use_id": "bundle-tool", "notification_type": "idle_prompt",
                           "last_assistant_message": "不应转发的回复"}
                for event, kind in (("SessionStart", "session_start"), ("UserPromptSubmit", "prompt"),
                                    ("PreToolUse", "working"), ("PostToolUse", "tool_done"),
                                    ("PostToolUseFailure", "tool_error"), ("Stop", "stop"),
                                    ("Notification", "notification")):
                    result = run(["--hook", event], payload)
                    require(not result.stdout and not result.stderr, f"silent-{event}")
                    require(mock.events[-1]["type"] == kind and mock.events[-1]["session"] == "临时会话",
                            f"stdin-event-{event}")
                    if event == "Stop":
                        require("detail" not in mock.events[-1], "stop-no-reply")
                    if event == "PreToolUse":
                        require("测试.txt" in mock.events[-1]["detail"], "utf8-stdin")
                for decision in ("allow", "deny", "gone"):
                    mock.decision = decision
                    result = run(["--hook", "PermissionRequest"], payload)
                    if decision == "gone":
                        require(not result.stdout, "permission-no-implicit-allow")
                    else:
                        output = json.loads(result.stdout)["hookSpecificOutput"]["decision"]
                        require(output["behavior"] == decision, f"permission-{decision}")
                        if decision == "deny":
                            require("诗音" in output["message"], "utf8-deny-output")
                mock.feedback = "测试反馈：继续加油"
                require(run(["--hook", "UserPromptSubmit"], payload).stdout.decode("utf-8").strip() == mock.feedback,
                        "utf8-feedback-output")
                require(json.loads(run(["--hook", "PostToolUse"], payload).stdout)["hookSpecificOutput"][
                    "additionalContext"] == mock.feedback, "feedback-json-output")
                mock.gate = {"stop": True}
                for event in ("PreToolUse", "PostToolUse"):
                    require(json.loads(run(["--hook", event], payload).stdout)["continue"] is False,
                            f"stop-output-{event}")
                result = run(["--hook", "PermissionRequest"], {**payload, "tool_name": "ExitPlanMode"})
                require(not result.stdout and mock.events[-1]["type"] == "plan_ready", "plan-ready-only")
            env["SHION_PORT"] = str(free_port())
            require(not run(["--hook", "Stop"]).stdout, "server-down-silent")
            require(json.loads(run(["--console-send", "--pid", "0", "--created", "0", "--text", "继续"],
                                   expected=1).stdout) == {"ok": False, "reason": "gone"}, "console-helper-json")

            # 无 mock 服务，SessionStart 必须自行启动同一复制路径的 exe。
            run(["--hook", "SessionStart"], {"session_id": "auto-launch"})
            port = int(env["SHION_PORT"])
            wait_for(lambda: http(port, "/health") == {"ok": True})
            pids = own_processes(exe)
            require(bool(pids), "session-start-launches-relocated-exe")
            report["launched_pids"] = pids
            data = Path(env["APPDATA"]) / "Shion"
            wait_for(lambda: (data / "state.json").is_file() and (data / "shion.log").is_file())
            require("SHION_DATA_DIR" not in env, "default-appdata-save-and-log")
            run(["--hook", "PreToolUse"], {"session_id": "auto-launch", "tool_name": "Read"})
            wait_for(lambda: "→ working" in (data / "shion.log").read_text(encoding="utf-8"))
            run(["--hook", "Stop"], {"session_id": "auto-launch"})
            wait_for(lambda: "→ done" in (data / "shion.log").read_text(encoding="utf-8"))
            require(True, "live-gui-hook-events")
            for name in ("state.json", "shion.log"):
                shutil.copy2(data / name, evidence / name)
            own_processes(exe, terminate=True)
            require(not own_processes(exe), "own-process-cleanup")
            require(before == manifest(relocated), "program-directory-unchanged")
            require(not list(relocated.rglob(".claude")), "no-config-in-program-directory")
            require(not list(relocated.rglob("python.exe")), "no-external-python-interpreter")
            report["ok"] = True
        except BaseException as exc:
            report.update(ok=False, error=str(exc))
            raise
        finally:
            own_processes(exe, terminate=True)
            (evidence / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
