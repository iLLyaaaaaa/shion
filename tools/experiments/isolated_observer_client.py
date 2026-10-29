"""Real Codex client, isolated CODEX_HOME, packaged MCP; no trust-db edits."""
import argparse
import json
import os
from pathlib import Path
import queue
import shutil
import statistics
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from shion.observer import ObservationServer
from shion.events import Observation
from tools import codex_config as config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    home, data = output / "codex-home", output / "data"
    data.mkdir(exist_ok=True)
    server = ObservationServer("a" * 64, port=0)
    server.start()
    (data / "chatgpt-observer.json").write_text(json.dumps({"enabled": True, "token": "a" * 64, "port": server.server.server_port}))
    config.apply_plan(config.install_plan(home, [str(args.exe.resolve()), "--codex-observer"], data))
    env = dict(os.environ, CODEX_HOME=str(home), HOME=str(output), USERPROFILE=str(output), APPDATA=str(output / "appdata"))
    messages = queue.Queue()
    report = {}
    with (output / "stderr.log").open("w", encoding="utf-8") as error:
        process = subprocess.Popen([shutil.which("codex"), "app-server", "--stdio"], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=error, text=True, encoding="utf-8", env=env, cwd=output)
        def reader():
            for line in process.stdout:
                messages.put(json.loads(line))
        threading.Thread(target=reader, daemon=True).start()
        def call(number, method, params):
            process.stdin.write(json.dumps({"id": number, "method": method, "params": params}) + "\n")
            process.stdin.flush()
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                reply = messages.get(timeout=max(.1, deadline-time.monotonic()))
                if reply.get("id") == number:
                    if "error" in reply:
                        raise RuntimeError(reply["error"])
                    return reply["result"]
            raise TimeoutError(method)
        try:
            report["client"] = call(1, "initialize", {"clientInfo": {"name": "shion_isolated_acceptance", "version": "2"}, "capabilities": {"experimentalApi": True}})
            process.stdin.write('{"method":"initialized"}\n')
            process.stdin.flush()
            account = call(2, "account/read", {"refreshToken": False})
            report["authenticated"] = account.get("account") is not None
            report["hooks"] = call(3, "hooks/list", {"cwds": [str(output)]})
            thread = call(4, "thread/start", {"cwd": str(output), "ephemeral": True, "sandbox": "read-only", "approvalPolicy": "on-request"})
            tid = thread["thread"]["id"]
            report["mcp_status"] = call(5, "mcpServerStatus/list", {"threadId": tid, "serverName": config.NAME})
            times = []
            count = 0
            for index in range(30):
                begin = time.perf_counter()
                reply = call(10 + index, "mcpServer/tool/call", {"threadId": tid, "server": config.NAME,
                    "tool": "observe_lifecycle", "arguments": {"event": "Stop", "source": "global", "session_id": "synthetic", "turn_id": str(index)}})
                assert reply["content"] == [{"type": "text", "text": "{}"}]
                assert reply.get("isError") is False
                assert reply.get("structuredContent") is None and reply.get("_meta") is None
                assert set(reply) <= {"content", "isError", "structuredContent", "_meta"}
                times.append((time.perf_counter()-begin)*1000)
                count += sum(isinstance(event, Observation) for event in server.inbox.drain())
            report["synthetic_mcp"] = {"sent": 30, "received": count, "median_ms": statistics.median(times), "p95_ms": sorted(times)[28], "max_ms": max(times)}
            report["actual_hook_events"] = 0
            report["trust_modified"] = False
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=10)
            server.stop()
            (output / "client-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"authenticated": report["authenticated"], "synthetic_mcp": report.get("synthetic_mcp"), "actual_hook_events": 0}))


if __name__ == "__main__":
    main()
