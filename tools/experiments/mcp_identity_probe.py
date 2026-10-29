"""Isolated, synthetic-data MCP launcher probe; never logs credentials or payloads."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    report = {"pid": os.getpid(), "parent_pid": os.getppid()}
    for name, flags in (("user", ["/user"]), ("groups", ["/groups"]), ("privileges", ["/priv"])):
        report[name] = subprocess.check_output(["whoami", *flags, "/fo", "csv", "/nh"], text=True)
    try:
        # Only point this probe at synthetic test data.
        (args.data_dir / "chatgpt-observer.json").read_bytes()
        report["credential_read"] = True
    except OSError as exc:
        report["credential_read"] = False
        report["read_error"] = exc.winerror
    args.report.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
    from shion.codex_mcp import main as serve
    return serve(["--data-dir", str(args.data_dir)])


if __name__ == "__main__":
    raise SystemExit(main())
