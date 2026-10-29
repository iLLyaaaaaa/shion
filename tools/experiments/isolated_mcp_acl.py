# 已废弃，仅作为决策记录保留
"""Start a real Codex app-server MCP connection, without a model turn or Hooks.

All generated config, sessions and synthetic credentials stay in --output.
The probe logs process identity, never credential content or conversations.
"""
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--desktop-proxy", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    from shion import private_store as secure
    from shion.observer import ObservationServer
    private = secure.ensure_directory(output / "private")
    fake = private / "chatgpt-observer.json"
    observer = ObservationServer("a" * 64, port=0)
    observer.start()
    secure.replace_private(fake, json.dumps({"token": "a" * 64,
        "port": observer.server.server_port, "enabled": True}).encode())
    home = output / "codex-home"
    home.mkdir(exist_ok=True)
    import tomlkit
    config = {"mcp_servers": {"shion_acl_probe": {
        "command": sys.executable,
        "args": ["-B", str(ROOT / "tools/experiments/mcp_identity_probe.py"),
                 "--report", str(output / "mcp-identity.json"), "--data-dir", str(private)],
        "startup_timeout_sec": 10}}}
    (home / "config.toml").write_text(tomlkit.dumps(config), encoding="utf-8")
    environment = dict(os.environ) if args.desktop_proxy else dict(os.environ, CODEX_HOME=str(home))
    lines = queue.Queue()
    with (output / "app-server.stderr.log").open("w", encoding="utf-8") as err:
        command = [shutil.which("codex"), "app-server", "proxy" if args.desktop_proxy else "--stdio"]
        process = subprocess.Popen(command,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, text=True,
            encoding="utf-8", env=environment, cwd=output)
        def reader():
            for line in process.stdout:
                lines.put(json.loads(line))
        threading.Thread(target=reader, daemon=True).start()
        def call(number, method, params):
            process.stdin.write(json.dumps({"id": number, "method": method, "params": params}) + "\n")
            process.stdin.flush()
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                message = lines.get(timeout=max(.1, deadline-time.monotonic()))
                if message.get("id") == number:
                    if "error" in message:
                        raise RuntimeError(message["error"])
                    return message["result"]
            raise TimeoutError(method)
        try:
            call(1, "initialize", {"clientInfo": {"name": "shion_acl_test", "version": "1"},
                                   "capabilities": {"experimentalApi": True}})
            process.stdin.write('{"method":"initialized"}\n')
            process.stdin.flush()
            params = {"cwd": str(output), "ephemeral": True,
                      "sandbox": "read-only", "approvalPolicy": "on-request"}
            if args.desktop_proxy:
                params["config"] = config
            thread = call(2, "thread/start", params)
            status = call(3, "mcpServerStatus/list", {"threadId": thread["thread"]["id"],
                                                       "serverName": "shion_acl_probe"})
            (output / "mcp-status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
            delays = []
            received = 0
            for index in range(20):
                start = time.perf_counter()
                result = call(10 + index, "mcpServer/tool/call", {
                    "threadId": thread["thread"]["id"], "server": "shion_acl_probe",
                    "tool": "observe_lifecycle", "arguments": {"event": "Stop", "source": "global",
                    "session_id": "synthetic-acl", "turn_id": str(index)}})
                delays.append((time.perf_counter() - start) * 1000)
                received += len(observer.inbox.drain())
            metrics = {"synthetic_events_received": received, "calls": len(delays),
                       "median_ms": statistics.median(delays), "p95_ms": sorted(delays)[18],
                       "max_ms": max(delays), "scope": "app-server MCP call roundtrip; not Hook/UI latency"}
            (output / "mcp-metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
            print(json.dumps({"identity_written": (output / "mcp-identity.json").exists(),
                              "status_written": True, "model_turns": 0, "hooks_installed": False}))
        finally:
            observer.stop()
            process.stdin.close()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=10)


if __name__ == "__main__":
    main()
