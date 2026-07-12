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

# ─ Scenario Configuration ───────────────────────────────────────────
import argparse

parser = argparse.ArgumentParser(description="ResQ Target Service")
parser.add_argument("--scenario", type=int, default=1, choices=[1, 2, 3, 4, 5],
                    help="Scenario number (1-5)")
args = parser.parse_args()
SCENARIO = args.scenario

# Scenario-specific failure timing
SCENARIO_FAILURE_DELAY = {
    1: 15,  # DB pool exhaustion
    2: 15,  # Cache failure
    3: 15,  # Queue failure
    4: 10,  # Memory leak (faster now)
    5: 15,  # External API failure
}

FAILURE_DELAY = SCENARIO_FAILURE_DELAY.get(SCENARIO, 15)

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

# ─ Message Queue Setup ──────────────────────────────────────────────
import queue as stdlib_queue
message_queue = stdlib_queue.Queue(maxsize=100)
queue_healthy = True
queue_errors = 0

# External API health (for scenario 5)
external_api_healthy = True

# Cache disabled flag (for scenario 2)
cache_disabled = False


def simulate_queue_failure(delay=15):
    """Simulate queue failure after delay (for scenario 3)."""
    global queue_healthy
    time.sleep(delay)
    queue_healthy = False
    logger.error("Message queue connection lost - all publishing will fail [file:target/app.py, func:simulate_queue_failure, line:95]")


def simulate_cache_failure(delay=15):
    """Simulate cache failure after delay (for scenario 2)."""
    global cache_hits, cache_misses, cache, cache_disabled
    time.sleep(delay)
    # Clear cache and disable it permanently
    cache.clear()
    cache_disabled = True
    cache_hits = 0
    cache_misses = 0
    logger.error("Cache service unavailable - all requests will miss cache [file:target/app.py, func:simulate_cache_failure, line:110]")


def simulate_memory_leak(delay=10):
    """Simulate memory leak by allocating memory over time (for scenario 4)."""
    global degraded
    leaked_memory = []
    time.sleep(delay)
    logger.warning("Memory leak detected - allocating memory continuously [file:target/app.py, func:simulate_memory_leak, line:115]")
    while True:
        # Allocate ~10MB every second
        leaked_memory.append(bytearray(10 * 1024 * 1024))
        time.sleep(1)
        # After 10 seconds of leaking, start causing errors
        if len(leaked_memory) > 10:
            degraded = True
            if len(leaked_memory) % 3 == 0:
                logger.error(f"Out of memory - service degraded ({len(leaked_memory) * 10}MB leaked) [file:target/app.py, func:simulate_memory_leak, line:125]")


def simulate_external_api_failure(delay=15):
    """Simulate external API failure (for scenario 5)."""
    global external_api_healthy
    time.sleep(delay)
    external_api_healthy = False
    logger.error("External payment API connection timeout - service unavailable [file:target/app.py, func:simulate_external_api_failure, line:130]")


def simulate_db_pool_exhaustion(delay=15):
    """Simulate DB connection pool exhaustion (for scenario 1)."""
    global db_pool_active, db_pool_exhausted
    time.sleep(delay)
    db_pool_active = DB_POOL_SIZE  # Pool is now full
    db_pool_exhausted = True
    logger.error(f"Database connection pool exhausted - {DB_POOL_SIZE}/{DB_POOL_SIZE} connections active [file:target/app.py, func:simulate_db_pool_exhaustion, line:140]")


# Start scenario-specific failure simulation
if SCENARIO == 1:
    threading.Thread(target=simulate_db_pool_exhaustion, args=(FAILURE_DELAY,), daemon=True).start()
elif SCENARIO == 2:
    threading.Thread(target=simulate_cache_failure, args=(FAILURE_DELAY,), daemon=True).start()
elif SCENARIO == 3:
    threading.Thread(target=simulate_queue_failure, args=(FAILURE_DELAY,), daemon=True).start()
elif SCENARIO == 4:
    threading.Thread(target=simulate_memory_leak, args=(FAILURE_DELAY,), daemon=True).start()
elif SCENARIO == 5:
    threading.Thread(target=simulate_external_api_failure, args=(FAILURE_DELAY,), daemon=True).start()

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

# DB Connection Pool simulation (scenario 1)
DB_POOL_SIZE = 500
db_pool_active = 0
db_pool_exhausted = False

# ── Cache (in-memory) ────────────────────────────────────────────────
cache = {}  # key -> {"data": ..., "expires": timestamp}
CACHE_TTL = 10  # seconds
cache_hits = 0
cache_misses = 0


def cache_get(key):
    """Get value from cache if not expired."""
    global cache_hits, cache_misses
    if cache_disabled:
        cache_misses += 1
        return None
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
    if cache_disabled:
        return
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
                "queue_healthy": queue_healthy,
                "queue_errors": queue_errors,
                "queue_size": message_queue.qsize(),
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
    global queue_errors
    start = time.time()
    
    try:
        # Check cache first
        cached = cache_get("users_list")
        if cached:
            latency = time.time() - start
            _record(latency)
            logger.info(f"GET /api/users — 200 — {int(latency * 1000)}ms — CACHE HIT [file:target/app.py, func:get_users, line:195]")
            return jsonify({"users": cached, "cached": True})

        # Cache miss - simulate DB overload from cache miss storm (scenario 2)
        if SCENARIO == 2 and cache_misses > 10:
            time.sleep(random.uniform(2, 5))  # DB is overloaded
            _record(time.time() - start, errored=True)
            import traceback
            tb = traceback.format_stack()[-3:]
            tb_str = "".join(tb)
            logger.error(f"Database query timeout - cache miss storm overwhelming DB [file:target/app.py, func:get_users, line:210]\nTraceback (most recent call last):\n{tb_str}")
            return jsonify({"error": "database timeout"}), 503

        # Memory leak causing OOM (scenario 4)
        if SCENARIO == 4 and degraded:
            time.sleep(random.uniform(3, 6))
            _record(time.time() - start, errored=True)
            import traceback
            tb = traceback.format_stack()[-3:]
            tb_str = "".join(tb)
            logger.error(f"Out of memory error - service unstable [file:target/app.py, func:get_users, line:220]\nTraceback (most recent call last):\n{tb_str}")
            return jsonify({"error": "service unavailable"}), 503
        
        conn = sqlite3.connect(DB_PATH, timeout=5)
        conn.row_factory = sqlite3.Row

        # Simulate DB pool exhaustion (scenario 1)
        if db_pool_exhausted and random.random() < 0.7:
            time.sleep(random.uniform(3, 6))  # Long wait for connection
            _record(time.time() - start, errored=True)
            import traceback
            tb = traceback.format_stack()[-3:]
            tb_str = "".join(tb)
            logger.error(f"Database connection timeout - pool exhausted ({DB_POOL_SIZE}/{DB_POOL_SIZE} active) [file:target/app.py, func:get_users, line:240]\nTraceback (most recent call last):\n{tb_str}")
            conn.close()
            return jsonify({"error": "database connection timeout"}), 503

        # Real database query
        cursor = conn.execute("SELECT id, name, email FROM users")
        users = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        # Cache the result
        cache_set("users_list", users)

        # Publish to message queue (for notification service)
        if queue_healthy:
            try:
                message_queue.put_nowait({"type": "user_query", "count": len(users), "timestamp": datetime.now().isoformat()})
            except stdlib_queue.Full:
                queue_errors += 1
                logger.error(f"Message queue full - cannot publish user query result [file:target/app.py, func:get_users, line:225]")
        else:
            # Scenario 3: Queue failure causes request failures
            if SCENARIO == 3:
                queue_errors += 1
                _record(time.time() - start, errored=True)
                import traceback
                tb = traceback.format_stack()[-3:]
                tb_str = "".join(tb)
                logger.error(f"Message queue unhealthy - request failed [file:target/app.py, func:get_users, line:230]\nTraceback (most recent call last):\n{tb_str}")
                return jsonify({"error": "message queue unavailable"}), 503
            else:
                queue_errors += 1
                logger.error(f"Message queue unhealthy - cannot publish user query result [file:target/app.py, func:get_users, line:235]")

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
    global queue_errors
    start = time.time()
    
    try:
        # Check cache first
        cached = cache_get("orders_list")
        if cached:
            latency = time.time() - start
            _record(latency)
            logger.info(f"GET /api/orders — 200 — {int(latency * 1000)}ms — CACHE HIT [file:target/app.py, func:get_orders, line:240]")
            return jsonify({"orders": cached, "cached": True})

        # Cache miss - simulate DB overload from cache miss storm (scenario 2)
        if SCENARIO == 2 and cache_misses > 10:
            time.sleep(random.uniform(2, 5))  # DB is overloaded
            _record(time.time() - start, errored=True)
            import traceback
            tb = traceback.format_stack()[-3:]
            tb_str = "".join(tb)
            logger.error(f"Database query timeout - cache miss storm overwhelming DB [file:target/app.py, func:get_orders, line:260]\nTraceback (most recent call last):\n{tb_str}")
            return jsonify({"error": "database timeout"}), 503

        # Memory leak causing OOM (scenario 4)
        if SCENARIO == 4 and degraded:
            time.sleep(random.uniform(3, 6))
            _record(time.time() - start, errored=True)
            import traceback
            tb = traceback.format_stack()[-3:]
            tb_str = "".join(tb)
            logger.error(f"Out of memory error - service unstable [file:target/app.py, func:get_orders, line:270]\nTraceback (most recent call last):\n{tb_str}")
            return jsonify({"error": "service unavailable"}), 503
        
        conn = sqlite3.connect(DB_PATH, timeout=5)
        conn.row_factory = sqlite3.Row

        # Simulate external API call for payment processing (scenario 5)
        if SCENARIO == 5 and not external_api_healthy:
            time.sleep(random.uniform(3, 6))  # Long timeout
            _record(time.time() - start, errored=True)
            import traceback
            tb = traceback.format_exc()
            logger.error(f"External payment API timeout after 5s - service unavailable [file:target/app.py, func:get_orders, line:265]\nTraceback (most recent call last):\n{tb}")
            conn.close()
            return jsonify({"error": "payment service unavailable"}), 503
        
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
            "queue_healthy": queue_healthy,
            "queue_errors": queue_errors,
            "queue_size": message_queue.qsize(),
            "external_api_healthy": external_api_healthy,
            "scenario": SCENARIO,
            "db_pool_active": db_pool_active,
            "db_pool_size": DB_POOL_SIZE,
            "db_pool_exhausted": db_pool_exhausted,
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
