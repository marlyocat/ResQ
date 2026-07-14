"""Load simulator — drives traffic at the flaskapp target so metrics move.

Usage:
    python demo/load_sim.py

Config (env vars):
    LOAD_TARGET   base URL to hit          (default http://localhost:5000)
    LOAD_WORKERS  number of worker threads (default 8)
    LOAD_DELAY    avg seconds between requests per worker (default 0.08)

Sends a steady stream of GET /api/items (plus a few POSTs). Once the app enters
its failure scenario, those reads start timing out — pushing error rate and p99
latency past ResQ's detection thresholds.
"""

import os
import random
import threading
import time

import requests

TARGET = os.environ.get("LOAD_TARGET", "http://localhost:5000")
WORKERS = int(os.environ.get("LOAD_WORKERS", "8"))
DELAY = float(os.environ.get("LOAD_DELAY", "0.08"))
stop = False


def _send_one():
    try:
        if random.random() < 0.1:
            requests.post(f"{TARGET}/api/items",
                          json={"name": f"item-{random.randint(1, 999)}"}, timeout=8)
        else:
            requests.get(f"{TARGET}/api/items", timeout=8)
    except Exception:
        pass


def _worker():
    while not stop:
        _send_one()
        time.sleep(random.uniform(DELAY * 0.5, DELAY * 1.5))


if __name__ == "__main__":
    print(f"Load simulator -> {TARGET}  ({WORKERS} workers, ~{DELAY}s delay)")
    threads = [threading.Thread(target=_worker, daemon=True) for _ in range(WORKERS)]
    for t in threads:
        t.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop = True
        print("\nLoad sim stopped.")
