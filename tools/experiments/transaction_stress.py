"""Isolated multi-process install/trust/uninstall/recovery stress. Synthetic only."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools import codex_config as C
from shion import observer_files as S
import tomlkit

COMMAND = [r"D:\desktop\tools\Shion-dev\Shion.exe", "--codex-observer"]


class Crash(BaseException):
    pass


def worker(output, iterations):
    output.mkdir(parents=True, exist_ok=True)
    stats = {"cases": 0, "normal_install_uninstall_cycles": 0, "crashes": 0,
             "recovery_crashes": 0, "recoveries": 0, "native_calls": 0, "native_errors": [], "failures": []}
    native, atomic = S._native_replace, C.atomic
    def observed(temporary, target):
        before, staged = S._state(target, True), S._state(temporary)
        stats["native_calls"] += 1
        try:
            return native(temporary, target)
        except OSError as exc:
            def same(path, expected, security=False):
                try:
                    return S._state(path, security) == expected
                except (OSError, ValueError):
                    return False
            stats["native_errors"].append({"winerror": exc.winerror, "target": target.name,
                "target_unchanged": same(target, before, True), "stage_unchanged": same(temporary, staged),
                "target_attributes_before": before[4], "path_characters": len(str(target))})
            raise
    S._native_replace = observed
    for index in range(iterations):
        home = output / f"case-{index}"
        home.mkdir()
        path = home / "config.toml"
        original = b'# synthetic\nnotify=["preserve"]\n[mcp_servers.foreign]\ncommand="foreign"\n'
        path.write_bytes(original)
        if index % 2:
            (home / "hooks.json").write_bytes(b'{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"foreign"}]}]}}\n')
        def install():
            return C.install_plan(home, COMMAND, home / "data")
        def snapshot():
            return {str(p.relative_to(home)): C.digest(C.read(p)) for p in (
                home / "config.toml", home / "hooks.json", C.ownership_path(home))}
        try:
            C.apply_plan(install())
            doc = tomlkit.parse(path.read_bytes().decode())
            states = {f"{home / 'hooks.json'}:{re.sub(r'(?<!^)(?=[A-Z])', '_', event).lower()}:0:0":
                {"enabled": index % 2 == 0, "trusted_hash": "sha256:" + "a" * 64} for event in C.hook_groups()}
            states["foreign"] = {"enabled": False, "trusted_hash": "keep"}
            doc["hooks"] = {"state": states}
            path.write_bytes(tomlkit.dumps(doc).encode())
            hooks_path = home / "hooks.json"
            hooks = json.loads(hooks_path.read_bytes())
            hooks["description"] = "保留外部配置"
            hooks["hooks"]["Stop"].append({"hooks": [{"type": "command", "command": "later-foreign"}]})
            hooks_path.write_bytes(json.dumps(hooks, ensure_ascii=False, indent=2).encode())
            assert not install().changes
            C.apply_plan(C.uninstall_plan(home))
            uninstalled = snapshot()
            assert tomlkit.parse(path.read_bytes().decode()).unwrap()["hooks"]["state"] == states
            assert b'command="foreign"' in path.read_bytes()
            assert C.NAME.encode() not in hooks_path.read_bytes()
            C.apply_plan(install())
            assert not install().changes
            C.apply_plan(C.uninstall_plan(home))
            assert snapshot() == uninstalled
            stats["normal_install_uninstall_cycles"] += 2
            action, point = ("install" if (index // 4) % 2 == 0 else "uninstall"), index % 4 + 1
            if action == "uninstall":
                C.apply_plan(install())
            before = snapshot()
            security = S._security_digest(path)
            proposal = install() if action == "install" else C.uninstall_plan(home)
            calls = [0]
            def crash(target, data, staging, **kwargs):
                atomic(target, data, staging, **kwargs)
                calls[0] += 1
                if calls[0] == point:
                    raise Crash()
            C.atomic = crash
            try:
                C.apply_plan(proposal)
                raise AssertionError("crash not reached")
            except Crash:
                stats["crashes"] += 1
            calls[0] = point - 1
            try:
                C.recover(home)
                raise AssertionError("recovery crash not reached")
            except Crash:
                stats["recovery_crashes"] += 1
            C.atomic = atomic
            assert C.recover(home) and not C.recover(home)
            stats["recoveries"] += 1
            assert snapshot() == before
            assert S._security_digest(path) == security
            assert not list(home.rglob("*.shion-stage"))
            if action == "uninstall":
                C.apply_plan(C.uninstall_plan(home))
            assert not C.uninstall_plan(home).changes
            stats["cases"] += 1
        except Exception as exc:
            # No automatic retry of a failed case; retain its entire synthetic
            # transaction evidence and count it as a failure.
            stats["failures"].append({"case": index, "type": type(exc).__name__,
                "winerror": getattr(exc, "winerror", None), "message": str(exc)[:300]})
        finally:
            C.atomic = atomic
    (output / "worker.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return bool(stats["failures"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=24)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    if args.worker:
        return worker(output, args.iterations)
    output.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    def run(index):
        directory = output / f"worker-{index}"
        env = dict(os.environ, HOME=str(directory), USERPROFILE=str(directory),
                   APPDATA=str(directory / "appdata"), CODEX_HOME=str(directory / "codex-home"),
                   SHION_DATA_DIR=str(directory / "shion"))
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", "--output", str(directory),
            "--iterations", str(args.iterations)], env=env, cwd=ROOT, capture_output=True, timeout=240)
        if result.returncode not in (0, 1) or not (directory / "worker.json").exists():
            raise RuntimeError(f"worker {index} exited {result.returncode}: {result.stderr[-500:]!r}")
        return json.loads((directory / "worker.json").read_text(encoding="utf-8"))
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(run, range(args.workers)))
    totals = {key: sum(r[key] for r in results) for key in ("cases", "normal_install_uninstall_cycles", "crashes", "recovery_crashes", "recoveries", "native_calls")}
    totals.update({"workers": args.workers, "seconds": time.monotonic() - start,
                   "native_errors": [e for r in results for e in r["native_errors"]],
                   "failures": [e for r in results for e in r["failures"]]})
    (output / "stress.json").write_text(json.dumps(totals, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(totals, ensure_ascii=False, indent=2))
    return bool(totals["failures"])


if __name__ == "__main__":
    raise SystemExit(main())
