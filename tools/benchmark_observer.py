"""Controlled synthetic metadata load; writes no client config and no chat content."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import http.client
import json
from pathlib import Path
import statistics
import sys
import threading
import time
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from shion.observer import ObservationServer
from shion.tasks import TaskLedger
from shion.events import ObserverHeartbeat
from shion.codex_mcp import HeartbeatSender
from shion.scheduler import Scheduler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--heartbeats", type=int, default=0, choices=range(33))
    parser.add_argument("--scheduler", action="store_true")
    args = parser.parse_args()
    server = ObservationServer("a" * 64, port=0)
    server.start()
    scheduler = Scheduler(enabled=True) if args.scheduler else None
    ledger = scheduler.ledger if scheduler else TaskLedger()
    latencies, failures = [], []
    sent = {}
    finished = threading.Event()
    queue_peak = 0
    pulses = 0
    def producer():
        start = time.monotonic()
        for i in range(args.seconds * 100):
            target = start + i / 100
            time.sleep(max(0, target - time.monotonic()))
            ident = str(i)
            data = {"event": "PreToolUse" if i % 20 < 10 else "PostToolUse",
                    "session_id": str(i % 10), "turn_id": "1", "tool_use_id": ident,
                    "source": "global"}
            if args.heartbeats:
                data.update(observer=f"synthetic-{i % args.heartbeats}", leased=True)
            sent[ident] = time.monotonic()
            conn = http.client.HTTPConnection("127.0.0.1", server.server.server_port, timeout=1)
            try:
                conn.request("POST", "/observe/v1", json.dumps(data), {"Authorization": "Bearer " + "a" * 64})
                status = conn.getresponse().status
                if status != 204:
                    failures.append(status)
            except OSError:
                failures.append("connection")
            finally:
                conn.close()
        finished.set()
    thread = threading.Thread(target=producer)
    try:
        with ExitStack() as stack:
            if args.heartbeats:
                # Fixed synthetic credential under the caller's output directory.
                from shion import observer_files as secure
                temp = stack.enter_context(tempfile.TemporaryDirectory(dir=args.out.parent))
                directory = secure.ensure_directory(Path(temp) / "private")
                secure.write_new(directory / "chatgpt-observer.json", json.dumps({"token": "a" * 64,
                    "port": server.server.server_port, "enabled": True}).encode())
                for i in range(args.heartbeats):
                    stack.enter_context(HeartbeatSender(directory, f"synthetic-{i}"))
            thread.start()
            while not finished.is_set() or not server.inbox.queue.empty():
                queue_peak = max(queue_peak, server.inbox.queue.qsize())
                for event in server.inbox.drain():
                    if isinstance(event, ObserverHeartbeat):
                        (scheduler.heartbeat if scheduler else ledger.heartbeat)(event)
                        pulses += 1
                    else:
                        (scheduler.observe if scheduler else ledger.accept)(event)
                        latencies.append((time.monotonic() - sent[event.tool_use_id]) * 1000)
                if scheduler:
                    scheduler.select()
                time.sleep(0.05)
            thread.join()
    finally:
        server.stop()
    result = {"kind": "synthetic HTTP to " + ("scheduler" if scheduler else "ledger") +
                       ", 50ms consumer, not real GUI/client timing",
              "seconds": args.seconds, "events": ledger.received, "sessions": len(ledger.tasks),
              "failures": failures, "queue_peak": queue_peak, "degraded": server.inbox.degraded.is_set(),
              "heartbeat_senders": args.heartbeats, "heartbeats_received": pulses,
              "latency_p95_ms": statistics.quantiles(latencies, n=100)[94],
              "latency_max_ms": max(latencies)}
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
    return int(bool(failures) or len(latencies) != args.seconds * 100 or result["latency_p95_ms"] >= 100)


if __name__ == "__main__":
    raise SystemExit(main())
