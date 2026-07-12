"""Load Simulator - hammers the target service to trigger an incident.

Usage:
    python demo/load_sim.py

Sends requests for ~50 seconds:
  0-15s   → normal traffic (~5 req/s)
  15-50s  → heavy traffic (~15 req/s)

Note: Does NOT trigger degradation - each scenario handles its own failure mode.
"""

import requests
import threading
import time
import sys
import random

TARGET = "http://localhost:5000"
stop = False


def _send_one():
    try:
        ep = random.choice(["/api/users", "/api/orders"])
        requests.get(f"{TARGET}{ep}", timeout=5)
    except Exception:
        pass


def _worker():
    while not stop:
        _send_one()
        time.sleep(random.uniform(0.03, 0.12))


print("=" * 50)
print("  ResQ Load Simulator")
print("=" * 50)
print()

# Phase 1: normal traffic
print("[Phase 1] Normal traffic - 5 workers, ~5 req/s")
threads = []
for _ in range(5):
    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    threads.append(t)

time.sleep(15)

# Phase 2: heavy traffic (no degradation trigger - scenario handles failure)
print("[Phase 2] Heavy traffic - 15 workers, ~15 req/s")
for _ in range(10):
    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    threads.append(t)

try:
    time.sleep(35)
except KeyboardInterrupt:
    pass

# Stop
print("[Done] Load sim finished.")
stop = True
