"""ResQ Dashboard — real-time incident monitoring and agent investigation view.

Usage:
    python dashboard/app.py

Runs on http://localhost:5001
Connects to target service on http://localhost:5000
"""

from flask import Flask, render_template, jsonify, Response
import threading
import time
import json
import os
import sys
import asyncio
import requests as req_lib
from datetime import datetime

# Add project root to path so we can import integrations/ and agents/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

app = Flask(__name__)

# ── Config ───────────────────────────────────────────────────────────
TARGET_URL = "http://localhost:5000"
POLL_INTERVAL = 1.5  # seconds

# ── Qwen Client (real LLM calls) ────────────────────────────────────
try:
    from integrations.qwen_client import QwenClient
    qwen = QwenClient()
    QWEN_AVAILABLE = True
    print("  Qwen API: connected")
except Exception as e:
    qwen = None
    QWEN_AVAILABLE = False
    print(f"  Qwen API: not available ({e})")
    print("  Using simulated agent responses")

# ── Shared State ─────────────────────────────────────────────────────
lock = threading.Lock()
metrics_history = []          # list of metric snapshots (max 120)
events = []                   # timeline events
investigation_active = False
investigation_result = {}
incident_id = 0
last_investigation_time = 0
INVESTIGATION_COOLDOWN = 60  # seconds between investigations
incident_metrics_snapshot = None  # metrics captured at incident detection time
incident_logs_snapshot = None  # logs captured at incident detection time
service_status = "unknown"    # ok | degraded | unreachable
current_metrics = {}


def add_event(agent, message, kind="info", severity="info"):
    events.append({
        "time": datetime.now().strftime("%H:%M:%S"),
        "agent": agent,
        "message": message,
        "kind": kind,
        "severity": severity,
    })
    if len(events) > 80:
        events.pop(0)


# ── Anomaly Detector ─────────────────────────────────────────────────
def check_anomaly(m):
    if m.get("error_rate", 0) > 8:
        return True
    if m.get("p99_latency_ms", 0) > 1500:
        return True
    return False


# ── Agent Simulations ────────────────────────────────────────────────
# When QWEN_AVAILABLE is True, these call the real Qwen API.
# When False, they produce realistic simulated output for demo purposes.

LOG_ANALYZER_PROMPT = """You are a senior SRE analyzing production logs to identify error patterns, unusual sequences, and potential root causes.

Analyze the provided logs and return a list of diagnostic hypotheses. For each hypothesis:
- State the suspected cause clearly
- Provide a confidence score (0.0-1.0)
- List specific evidence from the logs
- Assess severity (low/medium/high/critical)

Be specific and evidence-based. Do not speculate without log support.

Return your response as a JSON array of hypotheses in this exact format:
[
  {
    "cause": "Clear description of the root cause",
    "confidence": 0.85,
    "evidence": ["specific log line or pattern", "another evidence point"],
    "severity": "high"
  }
]"""

METRIC_MONITOR_PROMPT = """You are a monitoring specialist analyzing system metrics to detect anomalies, correlate across metrics, and propose root causes.

Analyze the provided metrics data and return a list of diagnostic hypotheses. For each hypothesis:
- State the suspected cause clearly
- Provide a confidence score (0.0-1.0) with evidence
- List specific metric anomalies and their deviations from baseline
- Assess severity (low/medium/high/critical)

Focus on cross-metric correlations.

Return your response as a JSON array of hypotheses in this exact format:
[
  {
    "cause": "Clear description of the root cause",
    "confidence": 0.85,
    "evidence": ["CPU at 95% (baseline: 40%)", "Memory at 89% (baseline: 55%)"],
    "severity": "high"
  }
]"""

COORDINATOR_PROMPT = """You are an incident commander coordinating between two specialist agents.

Each specialist has provided their independent diagnosis. Your job:
1. Compare their evidence and hypotheses
2. Identify areas of agreement and conflict
3. Resolve conflicts using evidence quality and cross-agent confirmation
4. Make a final root cause determination with clear justification
5. Produce an actionable remediation plan

Return your response as JSON:
{
  "root_cause": {
    "cause": "description",
    "confidence": 0.89,
    "severity": "critical",
    "evidence": ["evidence1", "evidence2"]
  },
  "justification": "why this root cause was selected",
  "action_plan": {
    "steps": ["step 1", "step 2", "step 3"]
  }
}"""


def _parse_json_response(text):
    """Extract JSON from LLM response (handles markdown code blocks, extra text)."""
    cleaned = text.strip()
    # Try markdown code blocks first
    if "```json" in cleaned:
        cleaned = cleaned.split("```json")[1].split("```")[0].strip()
    elif "```" in cleaned:
        cleaned = cleaned.split("```")[1].split("```")[0].strip()
    # Try to find JSON array or object in the text
    for start_char, end_char in [("[", "]"), ("{", "}")]:
        start = cleaned.find(start_char)
        end = cleaned.rfind(end_char)
        if start != -1 and end != -1 and end > start:
            candidate = cleaned[start:end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
    return json.loads(cleaned)


def _call_qwen(system_prompt, user_input):
    """Call Qwen API synchronously (wraps async client)."""
    if not QWEN_AVAILABLE:
        return None
    try:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(
            qwen.analyze_with_context(system_prompt=system_prompt, user_input=user_input)
        )
        loop.close()
        return result.get("raw_response", "")
    except Exception as e:
        print(f"  Qwen API error: {e}")
        return None

def run_log_analyzer():
    add_event("Log Analyzer", "Querying production logs...", "agent")

    # Use incident-time snapshot (captured when anomaly was detected)
    logs_data = incident_logs_snapshot or []
    if logs_data:
        log_text = "\n".join(
            f"{e['timestamp']} [{e['level']}] {e['service']}: {e['message']}"
            for e in logs_data
        )
        add_event("Log Analyzer", f"Analyzing {len(logs_data)} log entries from incident window", "agent")
    else:
        log_text = ""
        add_event("Log Analyzer", "No logs captured from incident window", "agent")

    # Try real Qwen API
    if QWEN_AVAILABLE and log_text:
        add_event("Log Analyzer", "Analyzing logs with Qwen...", "agent")
        user_input = f"Analyze the following production logs and identify potential root causes:\n\n{log_text}"
        raw = _call_qwen(LOG_ANALYZER_PROMPT, user_input)
        if raw:
            try:
                hypotheses = _parse_json_response(raw)
                if isinstance(hypotheses, list) and hypotheses:
                    add_event("Log Analyzer", f"Produced {len(hypotheses)} hypotheses (Qwen API)", "agent")
                    return {"status": "complete", "hypotheses": hypotheses}
            except (json.JSONDecodeError, KeyError):
                add_event("Log Analyzer", "Qwen response parsing failed, using fallback", "agent")

    # Fallback: simulated
    time.sleep(2)
    add_event("Log Analyzer", "Found 47 ERROR entries in 30s window", "agent")
    time.sleep(1.5)
    add_event("Log Analyzer", "Pattern detected: connection pool exhaustion", "agent")
    return {
        "status": "complete",
        "hypotheses": [
            {
                "cause": "Database connection pool exhausted",
                "confidence": 0.82,
                "evidence": [
                    "47 connection timeout errors in 30s",
                    "Pool at max capacity (500/500)",
                    "Cascading 503 errors across 3/5 instances",
                ],
                "severity": "critical",
            },
            {
                "cause": "Memory pressure causing OOM kills",
                "confidence": 0.45,
                "evidence": [
                    "Heap growth 1.8GB in 15 minutes",
                    "OOM kill candidate logged at 14:25:03",
                ],
                "severity": "high",
            },
        ],
    }


def run_metric_monitor():
    add_event("Metric Monitor", "Fetching system metrics...", "agent")

    # Use incident-time snapshot (captured when anomaly was detected)
    metrics_data = incident_metrics_snapshot or []
    if metrics_data:
        metrics_text = json.dumps(metrics_data, indent=2)
        add_event("Metric Monitor", f"Analyzing {len(metrics_data)} metric snapshots from incident window", "agent")
    else:
        metrics_text = ""
        add_event("Metric Monitor", "No metrics captured from incident window", "agent")

    # Try real Qwen API
    if QWEN_AVAILABLE and metrics_text:
        add_event("Metric Monitor", "Analyzing metrics with Qwen...", "agent")
        user_input = f"Analyze the following system metrics and identify anomalous patterns and potential root causes:\n\n{metrics_text}"
        raw = _call_qwen(METRIC_MONITOR_PROMPT, user_input)
        if raw:
            try:
                hypotheses = _parse_json_response(raw)
                if isinstance(hypotheses, list) and hypotheses:
                    add_event("Metric Monitor", f"Produced {len(hypotheses)} hypotheses (Qwen API)", "agent")
                    return {"status": "complete", "hypotheses": hypotheses}
            except (json.JSONDecodeError, KeyError):
                add_event("Metric Monitor", "Qwen response parsing failed, using fallback", "agent")

    # Fallback: simulated
    time.sleep(2)
    add_event("Metric Monitor", "CPU anomaly: 95.2% (baseline: 42%)", "agent")
    time.sleep(1.5)
    add_event("Metric Monitor", "Latency spike: p99 > 30s (baseline: 120ms)", "agent")
    time.sleep(1)
    return {
        "status": "complete",
        "hypotheses": [
            {
                "cause": "Cascading failure from DB saturation",
                "confidence": 0.74,
                "evidence": [
                    "CPU spike 42% → 95% in 6 minutes",
                    "P99 latency 120ms → 30,000ms",
                    "Error rate 0.5% → 45%",
                    "DB pool 120 → 500 (maxed out)",
                ],
                "severity": "critical",
            },
        ],
    }


def run_coordinator(log_hyps, met_hyps):
    add_event("Coordinator", "Arbitrating between agent hypotheses...", "coord")

    # Try real Qwen API
    if QWEN_AVAILABLE:
        add_event("Coordinator", "Running arbitration with Qwen...", "coord")
        user_input = (
            f"Two specialists have provided their diagnoses.\n\n"
            f"Log Analyzer hypotheses:\n{json.dumps(log_hyps, indent=2)}\n\n"
            f"Metric Monitor hypotheses:\n{json.dumps(met_hyps, indent=2)}\n\n"
            f"Compare their evidence, resolve conflicts, and determine the root cause."
        )
        raw = _call_qwen(COORDINATOR_PROMPT, user_input)
        if raw:
            try:
                result = _parse_json_response(raw)
                if isinstance(result, dict) and "root_cause" in result:
                    add_event("Coordinator", "Root cause determined (Qwen API)", "coord", "success")
                    return result
            except (json.JSONDecodeError, KeyError):
                add_event("Coordinator", "Qwen response parsing failed, using fallback", "coord")

    # Fallback: simulated
    time.sleep(2.5)
    add_event("Coordinator", "Cross-referencing evidence from both agents", "coord")
    time.sleep(1.5)
    add_event("Coordinator", "Root cause determined with high confidence", "coord", "success")
    return {
        "root_cause": {
            "cause": "Database connection pool exhaustion causing cascading service failure",
            "confidence": 0.89,
            "severity": "critical",
            "evidence": [
                "Both agents independently identified DB issues",
                "Connection pool at max (500/500)",
                "Cascading to API layer and load balancer",
            ],
        },
        "justification": "Log Analyzer found connection pool exhaustion (0.82). Metric Monitor found DB saturation cascade (0.74). Cross-agent confirmation: both point to database layer. Combined confidence: 0.89.",
        "action_plan": {
            "steps": [
                "Increase DB connection pool from 500 to 1000",
                "Add query timeout of 5s to prevent queue buildup",
                "Restart unhealthy API instances",
                "Enable connection pool monitoring alert at 80% capacity",
            ],
        },
    }


def run_remediation(action_plan):
    add_event("Runbook Executor", "Executing remediation plan...", "exec")
    steps = action_plan.get("steps", [])

    if QWEN_AVAILABLE and steps:
        add_event("Runbook Executor", "Processing plan with Qwen...", "exec")
        user_input = (
            f"Simulate the execution of the following remediation steps and report results for each:\n\n"
            + "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps))
        )
        raw = _call_qwen(
            "You are an operations engineer executing remediation actions. Report results for each step.",
            user_input,
        )
        if raw:
            for i, step in enumerate(steps):
                time.sleep(0.5)
                add_event("Runbook Executor", f"Step {i+1}/{len(steps)}: {step}", "exec")
            add_event("Runbook Executor", "All steps completed (Qwen API)", "exec", "success")
            return {"status": "completed", "steps_executed": len(steps)}

    # Fallback: simulated
    for i, step in enumerate(steps):
        time.sleep(1.5)
        add_event("Runbook Executor", f"Step {i + 1}/{len(steps)}: {step}", "exec")
    time.sleep(1)
    add_event("Runbook Executor", "All steps completed — service recovering", "exec", "success")
    return {"status": "completed", "steps_executed": len(steps)}


def run_postmortem():
    add_event("Post-Mortem Writer", "Generating incident report...", "doc")

    if QWEN_AVAILABLE:
        add_event("Post-Mortem Writer", "Generating report with Qwen...", "doc")
        # Build transcript from events
        transcript = "\n".join(
            f"[{e['time']}] {e['agent']}: {e['message']}" for e in events
        )
        user_input = (
            f"Generate a comprehensive incident post-mortem from the following transcript. "
            f"Include: Incident Summary, Timeline, Root Cause, Impact, Resolution, Action Items, Lessons Learned.\n\n"
            f"Transcript:\n{transcript}"
        )
        raw = _call_qwen(
            "You are a technical writer creating a comprehensive incident post-mortem. Be thorough, objective, and actionable.",
            user_input,
        )
        if raw:
            add_event("Post-Mortem Writer", "Report generated (Qwen API)", "doc", "success")
            return {"postmortem": raw}

    # Fallback: simulated
    time.sleep(3)
    add_event("Post-Mortem Writer", "Report generated — 7 sections, 12 action items", "doc", "success")
    return {
        "postmortem": (
            "## Incident Summary\n"
            "Database connection pool exhaustion caused cascading failure across service-api, "
            "service-db, and load-balancer. ~15,000 active sessions affected for 8 minutes.\n\n"
            "## Root Cause\n"
            "A slow query (15.2s) on the users table caused connection backlog. Pool reached "
            "max capacity (500). New requests queued, causing latency spike and 503 errors.\n\n"
            "## Timeline\n"
            "- 14:25:00 — Connection pool exhausted (active=500, max=500)\n"
            "- 14:25:01 — Request timeouts begin on /api/users\n"
            "- 14:25:03 — OOM kill candidate: heap 3.2GB\n"
            "- 14:25:05 — Slow query detected (15.2s execution)\n"
            "- 14:26:00 — Health check failures, instances marked unhealthy\n"
            "- 14:26:30 — Backend removed from load balancer pool\n"
            "- 14:27:00 — Cascading failures across 3/5 instances\n"
            "- 14:29:00 — 45% of requests returning 503\n\n"
            "## Action Items\n"
            "1. Add query timeout (5s) to prevent connection backlog\n"
            "2. Increase pool max from 500 to 1000\n"
            "3. Add connection pool alert at 80% threshold\n"
            "4. Implement circuit breaker for downstream DB calls\n"
            "5. Add slow query monitoring and auto-kill for queries > 10s"
        ),
    }


# ── Investigation Orchestrator ───────────────────────────────────────
def run_investigation():
    global investigation_active, investigation_result

    investigation_active = True
    investigation_result = {}
    add_event("System", "Incident detected — deploying ResQ agents", "alert")

    # Phase 1: parallel diagnosis
    add_event("System", "Phase 1: Parallel diagnosis", "system")
    log_result = run_log_analyzer()
    metric_result = run_metric_monitor()

    # Phase 2: coordination
    add_event("System", "Phase 2: Coordinator arbitration", "system")
    coord_result = run_coordinator(
        log_result["hypotheses"],
        metric_result["hypotheses"],
    )

    # Phase 3: remediation
    add_event("System", "Phase 3: Runbook execution", "system")
    exec_result = run_remediation(coord_result["action_plan"])

    # Phase 4: post-mortem
    add_event("System", "Phase 4: Post-mortem generation", "system")
    pm_result = run_postmortem()

    investigation_result = {
        "status": "complete",
        "log_analyzer": log_result,
        "metric_monitor": metric_result,
        "coordinator": coord_result,
        "runbook_executor": exec_result,
        "postmortem": pm_result,
    }
    investigation_active = False
    add_event("System", "Incident resolved — all agents complete", "success")


# ── Background Polling ───────────────────────────────────────────────
def poll_target():
    global service_status, current_metrics, last_investigation_time, incident_metrics_snapshot, incident_logs_snapshot
    while True:
        try:
            r = req_lib.get(f"{TARGET_URL}/api/metrics", timeout=3)
            if r.status_code == 200:
                m = r.json()
                current_metrics = m
                service_status = "degraded" if m.get("degraded") else "ok"

                with lock:
                    metrics_history.append(m)
                    if len(metrics_history) > 120:
                        metrics_history.pop(0)

                if check_anomaly(m) and not investigation_active:
                    now = time.time()
                    if now - last_investigation_time > INVESTIGATION_COOLDOWN:
                        last_investigation_time = now
                        # Capture snapshots at incident detection time
                        try:
                            mh = req_lib.get(f"{TARGET_URL}/api/metrics-history", timeout=5)
                            incident_metrics_snapshot = mh.json().get("history", [])
                        except Exception:
                            incident_metrics_snapshot = []
                        try:
                            lg = req_lib.get(f"{TARGET_URL}/api/logs", timeout=5)
                            incident_logs_snapshot = lg.json().get("logs", [])
                        except Exception:
                            incident_logs_snapshot = []
                        threading.Thread(target=run_investigation, daemon=True).start()
            else:
                service_status = "unreachable"
        except Exception:
            service_status = "unreachable"
        time.sleep(POLL_INTERVAL)


# ── Routes ───────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def status():
    with lock:
        return jsonify({
            "service_status": service_status,
            "current_metrics": current_metrics,
            "investigation_active": investigation_active,
            "investigation_result": investigation_result,
            "events": list(events),
            "metrics_history": list(metrics_history),
        })


@app.route("/api/stream")
def stream():
    def generate():
        last_event_count = 0
        while True:
            with lock:
                data = {
                    "service_status": service_status,
                    "current_metrics": current_metrics,
                    "investigation_active": investigation_active,
                    "investigation_result": investigation_result,
                    "events": events,
                    "metrics_history": metrics_history[-60:],
                }
            new_events = len(events) - last_event_count
            if new_events > 0:
                last_event_count = len(events)
                yield f"data: {json.dumps(data)}\n\n"
            else:
                # Send metrics-only update every 2s even without new events
                yield f"data: {json.dumps(data)}\n\n"
            time.sleep(1.5)

    return Response(generate(), mimetype="text/event-stream")


@app.route("/api/reset", methods=["POST"])
def reset():
    global investigation_active, investigation_result, incident_id
    with lock:
        metrics_history.clear()
        events.clear()
        investigation_active = False
        investigation_result = {}
        incident_id += 1
    add_event("System", "Dashboard reset — monitoring resumed", "system")
    return jsonify({"status": "reset"})


# ── Start ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    add_event("System", "ResQ Dashboard started — monitoring target on :5000", "system")
    threading.Thread(target=poll_target, daemon=True).start()
    print()
    print("=" * 50)
    print("  ResQ Dashboard")
    print("  http://localhost:5001")
    print("=" * 50)
    print()
    app.run(port=5001, debug=False, threaded=True)
