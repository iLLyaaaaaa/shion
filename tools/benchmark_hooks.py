r"""比较 exe 与 .venv 的 PreToolUse 启动到退出耗时；不连接真实诗音、不修改用户配置。"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
RUNS = 20


def main() -> None:
    sys.path.insert(0, str(ROOT))
    from tools.bundle_smoke import MockHooks

    exe = ROOT / "dist" / "Shion" / "Shion.exe"
    python = ROOT / ".venv" / "Scripts" / "python.exe"
    hook = ROOT / "hooks" / "shion_hook.py"
    commands = {"exe": [str(exe), "--hook", "PreToolUse"],
                "venv": [str(python), str(hook), "PreToolUse"]}
    samples = {name: [] for name in commands}
    payload = json.dumps({"session_id": "benchmark", "tool_use_id": "benchmark-read",
                          "tool_name": "Read", "tool_input": {"file_path": "benchmark.txt"}}).encode()
    with tempfile.TemporaryDirectory(prefix="Shion-hook-benchmark-") as directory, MockHooks() as mock:
        home = Path(directory)
        env = {**os.environ, "HOME": directory, "USERPROFILE": directory,
               "APPDATA": str(home / "AppData" / "Roaming"), "SHION_DATA_DIR": str(home / "Shion"),
               "SHION_PORT": str(mock.server.server_port)}
        drive, tail = os.path.splitdrive(directory)
        env.update(HOMEDRIVE=drive, HOMEPATH=tail)
        for i in range(RUNS):
            # 交替谁先跑，所有 20 次都计入，不丢弃首轮或预热。
            for name in (("exe", "venv") if i % 2 == 0 else ("venv", "exe")):
                count = len(mock.events)
                started = time.perf_counter_ns()
                result = subprocess.run(commands[name], input=payload, capture_output=True,
                                        cwd=ROOT, env=env, timeout=20,
                                        creationflags=subprocess.CREATE_NO_WINDOW)
                elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
                if (result.returncode != 0 or result.stdout or result.stderr
                        or len(mock.events) != count + 1
                        or mock.events[-1].get("type") != "working"
                        or mock.events[-1].get("session") != "benchmark"):
                    raise RuntimeError(f"{name} sample {i + 1} did not complete PreToolUse: {result!r}")
                samples[name].append(elapsed_ms)
        report = {
            "measured_at_utc": datetime.now(timezone.utc).isoformat(),
            "runs_per_command": RUNS,
            "condition": "Local HTTP mock, unpaused; identical synthetic Read input; isolated save/home; "
                         "alternating order; no warmup; subprocess creation through exit, including pipe IO.",
            "server": "tools.bundle_smoke.MockHooks on a random loopback port",
            "python_version": sys.version,
            "exe_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
            "hook_sha256": hashlib.sha256(hook.read_bytes()).hexdigest(),
            "commands": commands,
            "samples_ms": samples,
            "median_ms": {name: statistics.median(values) for name, values in samples.items()},
            "min_ms": {name: min(values) for name, values in samples.items()},
            "max_ms": {name: max(values) for name, values in samples.items()},
        }
    output = ROOT / "build" / "hook-benchmark.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    for name, median in report["median_ms"].items():
        print(f"{name}: n={RUNS}, median={median:.3f} ms")
    print(f"Evidence: {output}")


if __name__ == "__main__":
    main()
