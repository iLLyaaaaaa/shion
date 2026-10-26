"""Controlled synthetic metadata load; writes no client config and no chat content."""
from __future__ import annotations

import argparse
import http.client
import json
from pathlib import Path
import statistics
import sys
import threading
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from shion.observer import ObservationServer
from shion.tasks import TaskLedger


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    server = ObservationServer("a" * 64, port=0)
    server.start()
    ledger = TaskLedger()
    latencies, failures = [], []
    sent = {}
    finished = threading.Event()
    queue_peak = 0
    def producer():
        start = time.monotonic()
        for i in range(args.seconds * 100):
            target = start + i / 100
            time.sleep(max(0, target - time.monotonic()))
            ident = str(i)
            data = {"event": "PreToolUse" if i % 20 < 10 else "PostToolUse",
                    "session_id": str(i % 10), "turn_id": "1", "tool_use_id": ident,
                    "source": "global"}
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
    thread.start()
    try:
        while not finished.is_set() or not server.inbox.queue.empty():
            queue_peak = max(queue_peak, server.inbox.queue.qsize())
            for event in server.inbox.drain():
                ledger.accept(event)
                latencies.append((time.monotonic() - sent[event.tool_use_id]) * 1000)
            time.sleep(0.05)
        thread.join()
    finally:
        server.stop()
    result = {"kind": "synthetic HTTP to ledger, 50ms consumer, not real GUI/client timing",
              "seconds": args.seconds, "events": ledger.received, "sessions": len(ledger.tasks),
              "failures": failures, "queue_peak": queue_peak, "degraded": server.inbox.degraded.is_set(),
              "latency_p95_ms": statistics.quantiles(latencies, n=100)[94],
              "latency_max_ms": max(latencies)}
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
    return int(bool(failures) or len(latencies) != args.seconds * 100 or result["latency_p95_ms"] >= 100)


if __name__ == "__main__":
    raise SystemExit(main())
