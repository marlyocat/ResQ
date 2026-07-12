"""Target Service — simulates a production API that degrades under load.

Usage:
    python target/app.py

Runs on http://localhost:5000
"""

from flask import Flask, jsonify
import time
import random
import threading
import logging
import os
import sqlite3
import json
from datetime import datetime

try:
    import psutil
    PSUTIL_AVAILABLE = True
    proc_cpu = psutil.Process()
    proc_cpu.cpu_percent()  # First call initializes, returns 0
except ImportError:
    PSUTIL_AVAILABLE = False
    proc_cpu = None

app = Flask(__name__)

# ── Database Setup ───────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(__file__), "resq_demo.db")

def init_db():
    """Initialize SQLite database with sample data."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY, name TEXT, email TEXT, created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY, user_id INTEGER, total REAL, status TEXT, created_at TEXT
    )""")
    # Insert sample data if empty
    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:
        c.executemany("INSERT INTO users (name, email, created_at) VALUES (?, ?, ?)", [
            ("Alice", "alice@example.com", datetime.now().isoformat()),
            ("Bob", "bob@example.com", datetime.now().isoformat()),
            ("Charlie", "charlie@example.com", datetime.now().isoformat()),
        ])
        c.executemany("INSERT INTO orders (user_id, total, status, created_at) VALUES (?, ?, ?, ?)", [
            (1, 59.99, "shipped", datetime.now().isoformat()),
            (2, 129.50, "pending", datetime.now().isoformat()),
            (1, 24.99, "delivered", datetime.now().isoformat()),
        ])
    conn.commit()
    conn.close()

init_db()

# ── State ───────────────────────────────────────────────────────────
lock = threading.Lock()
request_count = 0
error_count = 0
latencies = []
degraded = False
start_time = datetime.utcnow().isoformat() + "Z"
log_buffer = []  # in-memory log ring buffer
MAX_LOG_BUFFER = 500
metrics_history = []  # rolling metrics snapshots
MAX_METRICS_HISTORY = 300

# ── Cache (in-memory) ────────────────────────────────────────────────
cache = {}  # key -> {"data": ..., "expires": timestamp}
CACHE_TTL = 10  # seconds
cache_hits = 0
cache_misses = 0


def cache_get(key):
    """Get value from cache if not expired."""
    global cache_hits, cache_misses
    if key in cache:
        entry = cache[key]
        if time.time() < entry["expires"]:
            cache_hits += 1
            return entry["data"]
        else:
            del cache[key]
    cache_misses += 1
    return None


def cache_set(key, data):
    """Set value in cache with TTL."""
    cache[key] = {
        "data": data,
        "expires": time.time() + CACHE_TTL
    }


def cache_clear():
    """Clear all cache entries."""
    global cache_hits, cache_misses
    cache.clear()
    cache_hits = 0
    cache_misses = 0

logging.basicConfig(
    level=logging.INFO,
    format='{"timestamp":"%(asctime)s","level":"%(levelname)s","service":"%(name)s","message":"%(message)s"}'
)
logger = logging.getLogger("target-service")


class BufferHandler(logging.Handler):
    def emit(self, record):
        entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "level": record.levelname,
            "service": record.name,
            "message": record.getMessage(),
        }
        with lock:
            log_buffer.append(entry)
            if len(log_buffer) > MAX_LOG_BUFFER:
                log_buffer.pop(0)

logger.addHandler(BufferHandler())


def _record_metrics_snapshot():
    """Background thread: record metrics snapshot every 2 seconds."""
    proc = psutil.Process() if PSUTIL_AVAILABLE else None
    while True:
        time.sleep(2)
        with lock:
            recent = latencies[-100:] if latencies else [0]
            sorted_lat = sorted(recent)
            n = len(sorted_lat)
            # CPU usage (cumulative since last call)
            if proc_cpu:
                cpu_pct = round(proc_cpu.cpu_percent(), 1)
            else:
                cpu_pct = round(os.cpu_percent(interval=0.5) or 0, 1)
            # Memory usage
            if proc:
                mem_mb = round(proc.memory_info().rss / 1024 / 1024, 1)
            else:
                mem_mb = 0
            
            total_cache = cache_hits + cache_misses
            cache_hit_rate = round((cache_hits / max(total_cache, 1)) * 100, 1)
            
            snapshot = {
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                "request_count": request_count,
                "error_count": error_count,
                "error_rate": round(error_count / max(request_count, 1) * 100, 1),
                "avg_latency_ms": round(sum(recent) / max(n, 1) * 1000, 1),
                "p50_latency_ms": round(sorted_lat[int(n * 0.50)] * 1000, 1) if n else 0,
                "p95_latency_ms": round(sorted_lat[min(int(n * 0.95), n - 1)] * 1000, 1) if n else 0,
                "p99_latency_ms": round(sorted_lat[min(int(n * 0.99), n - 1)] * 1000, 1) if n else 0,
                "cpu_pct": cpu_pct,
                "memory_mb": mem_mb,
                "cache_hits": cache_hits,
                "cache_misses": cache_misses,
                "cache_hit_rate": cache_hit_rate,
                "degraded": degraded,
            }
            metrics_history.append(snapshot)
            if len(metrics_history) > MAX_METRICS_HISTORY:
                metrics_history.pop(0)

threading.Thread(target=_record_metrics_snapshot, daemon=True).start()


# ── Helpers ──────────────────────────────────────────────────────────
def _record(latency, errored=False):
    global request_count, error_count
    with lock:
        request_count += 1
        if errored:
            error_count += 1
        latencies.append(latency)
        if len(latencies) > 1000:
            latencies.pop(0)


# ── Endpoints ───────────────────────────────────────────────────────
@app.route("/api/users")
def get_users():
    start = time.time()
    
    try:
        # Check cache first
        cached = cache_get("users_list")
        if cached:
            latency = time.time() - start
            _record(latency)
            logger.info(f"GET /api/users — 200 — {int(latency * 1000)}ms — CACHE HIT [file:target/app.py, func:get_users, line:195]")
            return jsonify({"users": cached, "cached": True})
        
        conn = sqlite3.connect(DB_PATH, timeout=5)
        conn.row_factory = sqlite3.Row
        
        if degraded and random.random() < 0.3:
            # Simulate slow query / connection exhaustion
            time.sleep(random.uniform(2, 5))
            _record(time.time() - start, errored=True)
            import traceback
            tb = traceback.format_stack()[-3:]
            tb_str = "".join(tb)
            logger.error(f"Database query timeout after 5s — connection pool exhausted [file:target/app.py, func:get_users, line:205]\nTraceback (most recent call last):\n{tb_str}")
            conn.close()
            return jsonify({"error": "database timeout"}), 503
        
        # Real database query
        cursor = conn.execute("SELECT id, name, email FROM users")
        users = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        # Cache the result
        cache_set("users_list", users)
        
        latency = time.time() - start
        _record(latency)
        logger.info(f"GET /api/users — 200 — {int(latency * 1000)}ms — returned {len(users)} users — CACHE MISS [file:target/app.py, func:get_users, line:220]")
        return jsonify({"users": users, "cached": False})
        
    except sqlite3.Error as e:
        _record(time.time() - start, errored=True)
        import traceback
        tb = traceback.format_exc()
        logger.error(f"SQLite error: {str(e)} [file:target/app.py, func:get_users, line:225]\nTraceback (most recent call last):\n{tb}")
        return jsonify({"error": "database error"}), 500


@app.route("/api/orders", methods=["GET"])
def get_orders():
    start = time.time()
    
    try:
        # Check cache first
        cached = cache_get("orders_list")
        if cached:
            latency = time.time() - start
            _record(latency)
            logger.info(f"GET /api/orders — 200 — {int(latency * 1000)}ms — CACHE HIT [file:target/app.py, func:get_orders, line:240]")
            return jsonify({"orders": cached, "cached": True})
        
        conn = sqlite3.connect(DB_PATH, timeout=5)
        conn.row_factory = sqlite3.Row
        
        if degraded and random.random() < 0.4:
            # Simulate connection refused / pool exhaustion
            time.sleep(random.uniform(1, 4))
            _record(time.time() - start, errored=True)
            import traceback
            tb = traceback.format_stack()[-3:]
            tb_str = "".join(tb)
            logger.error(f"Upstream database connection refused — all backends unhealthy [file:target/app.py, func:get_orders, line:255]\nTraceback (most recent call last):\n{tb_str}")
            conn.close()
            return jsonify({"error": "service unavailable"}), 503
        
        # Real database query with join
        cursor = conn.execute("""
            SELECT o.id, o.user_id, o.total, o.status, o.created_at, u.name as user_name
            FROM orders o JOIN users u ON o.user_id = u.id
        """)
        orders = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        # Cache the result
        cache_set("orders_list", orders)
        
        latency = time.time() - start
        _record(latency)
        logger.info(f"GET /api/orders — 200 — {int(latency * 1000)}ms — returned {len(orders)} orders — CACHE MISS [file:target/app.py, func:get_orders, line:275]")
        return jsonify({"orders": orders, "cached": False})
        
    except sqlite3.Error as e:
        _record(time.time() - start, errored=True)
        import traceback
        tb = traceback.format_exc()
        logger.error(f"SQLite error: {str(e)} [file:target/app.py, func:get_orders, line:280]\nTraceback (most recent call last):\n{tb}")
        return jsonify({"error": "database error"}), 500


@app.route("/api/health")
def health():
    return jsonify({"status": "ok" if not degraded else "degraded"})


@app.route("/api/metrics")
def metrics():
    with lock:
        recent = latencies[-100:] if latencies else [0]
        sorted_lat = sorted(recent)
        n = len(sorted_lat)
        # CPU: cumulative since last call
        if proc_cpu:
            cpu_pct = round(proc_cpu.cpu_percent(), 1)
        else:
            cpu_pct = round(os.cpu_percent(interval=0.5) or 0, 1)
        
        total_cache = cache_hits + cache_misses
        cache_hit_rate = round((cache_hits / max(total_cache, 1)) * 100, 1)
        
        return jsonify({
            "request_count": request_count,
            "error_count": error_count,
            "error_rate": round(error_count / max(request_count, 1) * 100, 1),
            "avg_latency_ms": round(sum(recent) / max(n, 1) * 1000, 1),
            "p50_latency_ms": round(sorted_lat[int(n * 0.50)] * 1000, 1) if n else 0,
            "p95_latency_ms": round(sorted_lat[min(int(n * 0.95), n - 1)] * 1000, 1) if n else 0,
            "p99_latency_ms": round(sorted_lat[min(int(n * 0.99), n - 1)] * 1000, 1) if n else 0,
            "cpu_pct": cpu_pct,
            "memory_mb": round(psutil.Process().memory_info().rss / 1024 / 1024, 1) if PSUTIL_AVAILABLE else 0,
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "cache_hit_rate": cache_hit_rate,
            "degraded": degraded,
            "uptime_since": start_time,
        })


@app.route("/api/degrade", methods=["POST"])
def degrade():
    global degraded
    degraded = True
    logger.critical("DEGRADATION MODE ENABLED — simulating cascading failure")
    return jsonify({"status": "degraded"})


@app.route("/api/recover", methods=["POST"])
def recover():
    global degraded, request_count, error_count
    degraded = False
    with lock:
        request_count = 0
        error_count = 0
    logger.info("Service recovered — metrics reset")
    return jsonify({"status": "recovered"})


@app.route("/api/logs")
def get_logs():
    with lock:
        return jsonify({"logs": list(log_buffer)})


@app.route("/api/metrics-history")
def get_metrics_history():
    """Return metrics history for a time window. Used by Metric Monitor for incident-period analysis."""
    with lock:
        return jsonify({"history": list(metrics_history)})


if __name__ == "__main__":
    logger.info("Target service starting on :5000")
    app.run(port=5000, debug=False, threaded=True)
