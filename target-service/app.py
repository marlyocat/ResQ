"""Instrumented Flask target service running on Alibaba Cloud.

A small business workload (an items API) that is fully instrumented against
four Alibaba Cloud resources:

    - SLS : every request/log is shipped to Simple Log Service in real time
    - OSS : reports/artifacts are persisted to Object Storage
    - ECS : infrastructure context (instances + status)
    - CMS : Cloud Monitor metrics for the host instance

It also doubles as a *target service* for ResQ's terminal UI: it serves
`/api/metrics` and `/api/logs` in the schema ResQ expects and can inject a
failure scenario (SCENARIO=1) so ResQ auto-detects and investigates an
incident. SLS log shipping keeps running throughout, so the cloud
integration is exercised while ResQ investigates locally.

Run (normal):
    python app.py

Run (ResQ TUI demo — port 5000 + incident after 15s):
    SCENARIO=1 PORT=5000 python app.py
"""

import logging
import os
import random
import threading
import time
import uuid
from collections import deque
from datetime import datetime

from flask import Flask, g, jsonify, request

from integrations.config import AlibabaConfig
from integrations.sls_client import SLSClient, SLSLogHandler
from integrations.oss_client import OSSClient
from integrations.ecs_client import ECSClient
from integrations.cms_client import CMSClient

try:
    import psutil
    _proc = psutil.Process()
    _proc.cpu_percent()  # prime — first call always returns 0.0
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    _proc = None

APP_FILE = os.path.abspath(__file__)

# ── Config + integration clients ─────────────────────────────────────────
config = AlibabaConfig()
sls = SLSClient(config)
oss = OSSClient(config)
ecs = ECSClient(config)
cms = CMSClient(config)

# ── Scenario (incident injection for the ResQ TUI) ───────────────────────
# 0 = off, 1 = DB pool exhaustion (unambiguous), 2 = cache failure disguised as
# a memory leak (ambiguous — logs point at memory, metrics point at cache; this
# is what makes the Log Analyzer and Metric Monitor disagree so the negotiation
# round has to resolve the conflict).
SCENARIO = int(os.getenv("SCENARIO", "0"))
FAILURE_DELAY = int(os.getenv("FAILURE_DELAY", "15"))
degraded = False
incident_type = "db_pool"                # "db_pool" | "cache"
_cache_incident_stop = threading.Event()

# ── Logging: console + SLS shipping + local ring buffer ──────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("flaskapp")
if config.sls_enabled:
    logger.addHandler(SLSLogHandler(sls))
    sls.start()
    logger.info("SLS log shipping enabled -> %s/%s",
                config.sls_project, config.sls_logstore)
else:
    logger.warning("SLS not configured — logs stay local. See .env.example")

app = Flask(__name__)

# ── In-memory state ──────────────────────────────────────────────────────
_items = {}
_metrics = {"request_count": 0, "error_count": 0, "latencies_ms": deque(maxlen=1000)}
_log_buffer = deque(maxlen=500)  # ResQ-TUI-shaped log entries
_lock = threading.Lock()


def log_event(level: str, message: str, **fields):
    """Emit a structured log line: ship to SLS + keep in the local buffer.

    The local buffer is what ResQ's terminal reads via /api/logs (instant,
    no ingestion lag); SLS receives the same line for the cloud integration.
    """
    logger.log(getattr(logging, level, logging.INFO), message, extra={"fields": fields})
    entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "level": level,
        "service": fields.get("service", "flaskapp"),
        "message": message,
    }
    with _lock:
        _log_buffer.append(entry)


# ── Request instrumentation ──────────────────────────────────────────────
@app.before_request
def _start_timer():
    g.start = time.time()
    g.request_id = uuid.uuid4().hex[:12]


@app.after_request
def _record_request(response):
    latency_ms = round((time.time() - getattr(g, "start", time.time())) * 1000, 1)
    with _lock:
        _metrics["request_count"] += 1
        if response.status_code >= 500:
            _metrics["error_count"] += 1
        _metrics["latencies_ms"].append(latency_ms)

    log_event(
        "ERROR" if response.status_code >= 500 else "INFO",
        f"{request.method} {request.path} -> {response.status_code} ({latency_ms}ms)",
        request_id=getattr(g, "request_id", ""),
        method=request.method,
        path=request.path,
        status=response.status_code,
        latency_ms=latency_ms,
    )
    return response


# ── Failure scenarios (for the ResQ TUI demo) ────────────────────────────
def _cache_incident_log_loop():
    """Flood the log with ONLY memory/GC 'red herring' lines while the cache
    incident is active — no cache or database terms appear in the logs at all.
    The true cause (a cache-hit-rate collapse, with memory staying bounded) shows
    up ONLY in the metrics. So the Log Analyzer (reads logs) concludes 'memory
    leak' while the Metric Monitor (reads metrics) concludes 'cache failure' —
    a genuine disagreement the negotiation round must resolve."""
    heap = 2.4
    while not _cache_incident_stop.is_set() and degraded:
        heap = min(3.2, heap + 0.1)  # the LOG claims a rising heap (the decoy)...
        log_event("WARN", f"heap usage climbing: {heap:.1f}GB / 4GB, allocation rate elevated", service="flaskapp")
        log_event("WARN", f"GC pause {random.randint(420, 680)}ms (full GC), throughput degraded", service="flaskapp")
        log_event("WARN", "high memory pressure — request buffers accumulating on the heap", service="flaskapp")
        log_event("ERROR", f"OOM candidate flagged by memory watchdog (heap {heap:.1f}GB)", service="flaskapp")
        _cache_incident_stop.wait(2.0)


def _start_incident(kind: str):
    global degraded, incident_type
    incident_type = "cache" if kind == "cache" else "db_pool"
    degraded = True
    if incident_type == "cache":
        _cache_incident_stop.clear()
        threading.Thread(target=_cache_incident_log_loop, daemon=True).start()
    else:
        log_event(
            "ERROR",
            f"Database connection pool exhausted — all connections in use "
            f"[file:{APP_FILE}, func:list_items, line:170]",
            service="flaskapp-db",
        )


def _stop_incident():
    global degraded
    degraded = False
    _cache_incident_stop.set()


def _degrade_after(delay: int):
    time.sleep(delay)
    _start_incident("cache" if SCENARIO == 2 else "db_pool")


if SCENARIO:
    threading.Thread(target=_degrade_after, args=(FAILURE_DELAY,), daemon=True).start()


# ── Workload endpoints (the "target service") ────────────────────────────
@app.route("/api/items", methods=["GET"])
def list_items():
    # When degraded, most reads fail — the failure mode depends on the scenario.
    if degraded and random.random() < 0.7:
        time.sleep(random.uniform(2.0, 5.0))
        if incident_type == "cache":
            # Memory-themed failure text only — keeps the cache signal out of the logs.
            log_event(
                "ERROR",
                "request failed — worker stalled under sustained memory pressure",
                service="flaskapp",
            )
            return jsonify({"error": "service overloaded"}), 503
        log_event(
            "ERROR",
            f"Database connection timeout — pool exhausted, request failed "
            f"[file:{APP_FILE}, func:list_items, line:170]",
            service="flaskapp-db",
        )
        return jsonify({"error": "database connection timeout"}), 503
    return jsonify({"items": list(_items.values()), "count": len(_items)})


@app.route("/api/items", methods=["POST"])
def create_item():
    data = request.get_json(silent=True) or {}
    if "name" not in data:
        return jsonify({"error": "field 'name' is required"}), 400
    item_id = uuid.uuid4().hex[:8]
    item = {
        "id": item_id,
        "name": data["name"],
        "value": data.get("value"),
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    _items[item_id] = item
    log_event("INFO", f"item created: {item_id}", item_id=item_id, name=item["name"])
    return jsonify(item), 201


@app.route("/api/items/<item_id>", methods=["GET"])
def get_item(item_id):
    item = _items.get(item_id)
    if not item:
        return jsonify({"error": "not found"}), 404
    return jsonify(item)


# ── Metrics (schema compatible with ResQ's terminal) ─────────────────────
def _percentiles():
    with _lock:
        lat = sorted(_metrics["latencies_ms"]) or [0]
        rc = _metrics["request_count"]
        ec = _metrics["error_count"]
    n = len(lat)
    return {
        "request_count": rc,
        "error_count": ec,
        "error_rate": round(ec / max(rc, 1) * 100, 1),        # ResQ reads this
        "error_rate_pct": round(ec / max(rc, 1) * 100, 1),    # alias
        "avg_latency_ms": round(sum(lat) / max(n, 1), 1),
        "p50_latency_ms": lat[int(n * 0.50)],
        "p95_latency_ms": lat[min(int(n * 0.95), n - 1)],
        "p99_latency_ms": lat[min(int(n * 0.99), n - 1)],
    }


@app.route("/api/metrics")
def metrics():
    body = _percentiles()
    cache_incident = degraded and incident_type == "cache"
    body.update({
        "cpu_pct": round(_proc.cpu_percent(), 1) if PSUTIL_AVAILABLE else 0.0,
        # Real RSS — stays bounded (~tens of MB), which argues AGAINST a memory leak
        # despite the memory-themed logs. This is the tell that points at the cache.
        "memory_mb": round(_proc.memory_info().rss / 1024 / 1024, 1) if PSUTIL_AVAILABLE else 0.0,
        "cache_hit_rate": 5.0 if cache_incident else 100.0,
        "db_query_latency_ms": round(random.uniform(2400, 3200)) if cache_incident else round(random.uniform(30, 60)),
        "queue_healthy": True,
        "queue_errors": 0,
        "degraded": degraded,
        "incident_type": incident_type if degraded else None,
        "scenario": SCENARIO,
        "items_stored": len(_items),
    })
    return jsonify(body)


# ── Health + integration status ──────────────────────────────────────────
@app.route("/api/health")
def health():
    return jsonify({
        "status": "degraded" if degraded else "ok",
        "time": datetime.utcnow().isoformat() + "Z",
    })


@app.route("/api/status")
def status():
    """Report which Alibaba integrations are configured and reachable."""
    body = {
        "config": config.summary(),
        "config_issues": config.validate(),
        "sls": sls.stats(),
    }
    if config.oss_enabled:
        body["oss"] = {"healthy": oss.health_check(), "bucket": config.oss_bucket_name}
    return jsonify(body)


# ── Logs: local buffer (ResQ TUI) + SLS query (cloud) ────────────────────
@app.route("/api/logs")
def get_logs():
    """Return recent logs. Default: local ring buffer (what ResQ's TUI reads).
    Pass ?source=sls to query them back from Alibaba SLS instead."""
    if request.args.get("source") == "sls":
        q = request.args.get("query", "*")
        minutes = int(request.args.get("minutes", "30"))
        lines = int(request.args.get("lines", "100"))
        try:
            return jsonify({"logs": sls.query(query=q, lookback_minutes=minutes, lines=lines)})
        except Exception as e:  # noqa: BLE001
            return jsonify({"error": str(e)}), 503
    with _lock:
        return jsonify({"logs": list(_log_buffer)})


# ── OSS: store / retrieve reports ────────────────────────────────────────
@app.route("/api/reports", methods=["POST"])
def create_report():
    report = request.get_json(silent=True) or {}
    report_id = report.get("id") or uuid.uuid4().hex[:12]
    report.setdefault("id", report_id)
    report.setdefault("generated_at", datetime.utcnow().isoformat() + "Z")
    try:
        key = oss.upload_report(report_id, report)
        log_event("INFO", f"report stored to OSS: {key}", report_id=report_id, oss_key=key)
        return jsonify({"report_id": report_id, "oss_key": key}), 201
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 503


@app.route("/api/reports", methods=["GET"])
def list_reports():
    date = request.args.get("date")
    try:
        return jsonify({"reports": oss.list_reports(date=date)})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 503


@app.route("/api/reports/<report_id>", methods=["GET"])
def fetch_report(report_id):
    date = request.args.get("date")
    report = oss.get_report(report_id, date=date)
    if report is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(report)


# ── ECS: infrastructure context ──────────────────────────────────────────
@app.route("/api/instances")
def instances():
    try:
        return jsonify({"instances": ecs.list_instances()})
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 503


# ── CMS: cloud monitor metrics ───────────────────────────────────────────
@app.route("/api/cloud-metrics")
def cloud_metrics():
    metric = request.args.get("metric", "CPUUtilization")
    dims = {"instanceId": config.ecs_instance_id} if config.ecs_instance_id else None
    try:
        return jsonify({
            "metric": metric,
            "namespace": config.cms_namespace,
            "datapoints": cms.get_metric_last(metric, dimensions=dims),
        })
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)}), 503


@app.route("/api/scenario", methods=["POST"])
def set_scenario():
    """Trigger or clear an incident on demand (for remote ResQ TUI demos).
    Body: {"action": "start", "type": "db_pool" | "cache"} or {"action": "stop"}.

    - type "db_pool" (default): unambiguous — agents agree, no negotiation needed.
    - type "cache": ambiguous — logs point at a memory leak, metrics point at a
      cache failure; the agents disagree and the negotiation round resolves it.
    """
    body = request.get_json(silent=True) or {}
    action = body.get("action", "start")
    kind = body.get("type", "db_pool")
    if action == "start":
        _start_incident(kind)
        # Neutral trigger line — must not reveal the incident type in the log stream
        # (the Log Analyzer reads these logs; the cache signal lives only in metrics).
        log_event("ERROR", "Incident triggered — service degradation detected", service="flaskapp")
        return jsonify({"degraded": True, "incident_type": incident_type})
    if action == "stop":
        _stop_incident()
        log_event("INFO", "Incident cleared — service recovered")
        return jsonify({"degraded": False})
    return jsonify({"error": "action must be 'start' or 'stop'"}), 400


@app.route("/")
def index():
    return jsonify({
        "service": "flaskapp (Alibaba-instrumented target service)",
        "integrations": config.enabled_map(),
        "scenario": SCENARIO,
        "degraded": degraded,
    })


if __name__ == "__main__":
    port = int(os.getenv("PORT", str(config.port)))
    for issue in config.validate():
        logger.warning("config: %s", issue)
    if SCENARIO:
        logger.info("SCENARIO=%d active — incident in %ds", SCENARIO, FAILURE_DELAY)
    logger.info("Starting flaskapp on :%d", port)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
