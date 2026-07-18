"""ResQ Terminal UI — interactive incident response in the terminal.

Usage:
    python demo/resq_terminal.py

Or run the full demo:
    python demo/run_demo.py

Controls:
    ↑/↓ or j/k  — scroll up/down
    Tab          — switch focus between panels
    q            — quit
"""

import time
import json
import sys
import os
import threading
import requests
from datetime import datetime

from textual.app import App, ComposeResult
from textual.containers import Vertical, Horizontal, VerticalScroll
from textual.widgets import Header, Footer, Static, RichLog
from textual.reactive import reactive
from textual import on

# Add project root for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Target service to monitor. Override to point at a remote host (e.g. an
# Alibaba ECS instance running flaskapp): set RESQ_TARGET_URL=http://<ip>:8000
TARGET_URL = os.environ.get("RESQ_TARGET_URL", "http://localhost:5000")

# ── Agent Colors (consistent across all views) ───────────────────────
AGENT_COLORS = {
    "Log Analyzer": "blue",
    "Metric Monitor": "magenta",
    "Coordinator": "yellow",
    "Runbook Executor": "green",
    "Post-Mortem Writer": "cyan",
    "System": "dim",
}

AGENT_ICONS = {
    "Log Analyzer": "📝",
    "Metric Monitor": "📊",
    "Coordinator": "🧠",
    "Runbook Executor": "🔧",
    "Post-Mortem Writer": "📋",
}

#  Qwen Client ──────────────────────────────────────────────────────
# Add project root to path for imports
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables from .env
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

# Shared negotiation logic (same prompt + conflict detection as the batch path)
from core.negotiation import NEGOTIATION_SUFFIX, causes_agree, CONFLICT_CHECK_SYSTEM

try:
    from integrations.qwen_client import QwenClient
    import asyncio
    qwen = QwenClient()
    QWEN_AVAILABLE = True
except Exception as e:
    qwen = None
    QWEN_AVAILABLE = False
    print(f"Qwen API not available: {e}")

# ── Shared State ─────────────────────────────────────────────────────
state = {
    "status": "monitoring",
    "incident_time": None,
    "incident_start": None,
    "incident_end": None,
    "metrics": {},
    "metrics_history": [],
    "peak_metrics": {},  # peak values during incident
    "events": [],
    "agents": {
        "log_analyzer": {"status": "idle", "findings": [], "message": "Waiting for incident..."},
        "metric_monitor": {"status": "idle", "findings": [], "message": "Waiting for incident..."},
        "coordinator": {"status": "idle", "findings": [], "message": "Waiting for agent reports..."},
        "runbook_executor": {"status": "idle", "findings": [], "message": "Waiting for action plan..."},
        "postmortem_writer": {"status": "idle", "findings": [], "message": "Waiting for resolution..."},
    },
    "root_cause": None,
    "action_plan": None,
    "postmortem": None,
    "oss_report_key": None,
    "negotiation": {
        "status": "idle",          # idle | running | done
        "disagreement": None,
        "log_before": "", "metric_before": "",
        "log_after": "", "metric_after": "",
        "resolved": None,          # agreement | revised
    },
}

# ── Agent Prompts ────────────────────────────────────────────────────
LOG_ANALYZER_PROMPT = """You are a senior SRE analyzing production logs AND source code to identify the exact code causing errors.

When you find error patterns in logs:
1. Identify the file, function, and line number from the log entries
2. Read the source code at that location
3. Analyze the error stack trace
4. Explain what the code does and why it's failing
5. Explain what the stack trace reveals about the error flow
6. Explain WHY you believe this code is the root cause

Return a JSON array of hypotheses:
[{"cause": "description", "confidence": 0.85, "evidence": ["evidence1"], "severity": "high", "code_location": {"file": "path/to/file.py", "function": "func_name", "line": 123}, "analysis": "Explanation of the code, stack trace, and why this is the root cause"}]"""

METRIC_MONITOR_PROMPT = """You are a monitoring specialist analyzing metrics. Return a JSON array of hypotheses:
[{"cause": "description", "confidence": 0.85, "evidence": ["evidence1"], "severity": "high"}]"""

COORDINATOR_PROMPT = """You are an incident commander. Compare hypotheses and determine root cause.

IMPORTANT: When providing action plans, base recommendations ONLY on the evidence provided. Do not assume specific configuration values (like pool sizes, timeouts, etc.) unless they are explicitly mentioned in the evidence. Instead:
- Identify what needs to be investigated or adjusted
- Recommend checking current configurations before making changes
- Suggest monitoring and validation steps
- Provide general guidance, not specific numbers

Return JSON:
{"root_cause": {"cause": "description", "confidence": 0.89, "severity": "critical", "evidence": ["e1"]}, "justification": "why", "action_plan": {"steps": ["Investigate current X configuration", "Monitor Y metric after change", "Validate Z behavior"]}}"""


def _parse_json(text):
    cleaned = text.strip()
    if "```json" in cleaned:
        cleaned = cleaned.split("```json")[1].split("```")[0].strip()
    elif "```" in cleaned:
        cleaned = cleaned.split("```")[1].split("```")[0].strip()
    for s, e in [("[", "]"), ("{", "}")]:
        si, ei = cleaned.find(s), cleaned.rfind(e)
        if si != -1 and ei > si:
            try:
                return json.loads(cleaned[si:ei + 1])
            except json.JSONDecodeError:
                continue
    return json.loads(cleaned)


def _read_source_code(file_path, line_number, context_lines=5, function=None):
    """Read source around an error location.

    Prefers the function definition as the anchor (robust to stale/approximate
    line numbers in log markers); falls back to the reported line number.
    """
    try:
        # Handle relative paths
        if not os.path.isabs(file_path):
            file_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), file_path)

        # The model often invents a plausible-but-nonexistent path (and remote
        # targets don't share our filesystem). If we can't see the file, skip the
        # source snippet entirely rather than surfacing a raw OS error.
        if not os.path.isfile(file_path):
            return None

        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        # Coerce the reported line to an int if possible.
        try:
            anchor = int(line_number)
        except (TypeError, ValueError):
            anchor = None

        # Prefer anchoring on the function definition if we have its name.
        if function:
            import re as _re
            pat = _re.compile(rf"\bdef\s+{_re.escape(str(function))}\s*\(")
            for i, ln in enumerate(lines, 1):
                if pat.search(ln):
                    anchor = i
                    break

        if not anchor or anchor < 1:
            anchor = 1

        start = max(0, anchor - context_lines - 1)
        end = min(len(lines), anchor + context_lines)

        code_context = []
        for i in range(start, end):
            marker = " >>> " if i + 1 == anchor else "     "
            code_context.append(f"{marker}{i+1:4d}: {lines[i].rstrip()}")

        return "\n".join(code_context)
    except Exception:
        # Never surface a raw read error into the UI — just omit the snippet.
        return None


def _call_qwen(system_prompt, user_input):
    if not QWEN_AVAILABLE:
        return None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(
            qwen.analyze_with_context(system_prompt=system_prompt, user_input=user_input)
        )
        loop.close()
        return result.get("raw_response", "")
    except Exception as e:
        print(f"Qwen API error: {e}")
        return None


def add_event(agent, message):
    state["events"].append({
        "time": datetime.now().strftime("%H:%M:%S"),
        "agent": agent,
        "message": message,
    })
    if len(state["events"]) > 100:
        state["events"].pop(0)


# ── Agent Functions ──────────────────────────────────────────────────
def run_log_analyzer(logs_data):
    agent = state["agents"]["log_analyzer"]
    agent["status"] = "running"
    agent["message"] = f"Analyzing {len(logs_data)} log entries..."
    add_event("Log Analyzer", f"Querying {len(logs_data)} log entries from incident window")

    log_text = "\n".join(
        f"{e['timestamp']} [{e['level']}] {e['service']}: {e['message']}"
        for e in logs_data
    )

    if QWEN_AVAILABLE and log_text:
        agent["message"] = "Calling Qwen API..."
        add_event("Log Analyzer", "Analyzing logs with Qwen Cloud API")
        raw = _call_qwen(LOG_ANALYZER_PROMPT, f"Analyze these production logs:\n\n{log_text}")
        if raw:
            try:
                hypotheses = _parse_json(raw)
                if isinstance(hypotheses, list) and hypotheses:
                    # Read source code for each hypothesis with code_location
                    for h in hypotheses:
                        code_loc = h.get("code_location")
                        if code_loc and code_loc.get("file") and code_loc.get("line"):
                            source = _read_source_code(code_loc["file"], code_loc["line"],
                                                       function=code_loc.get("function"))
                            if source:
                                h["source_code"] = source
                                add_event("Log Analyzer", f"Read source: {code_loc['file']}:{code_loc['line']}")
                    
                    agent["findings"] = hypotheses
                    agent["status"] = "done"
                    agent["message"] = f"Produced {len(hypotheses)} hypotheses (Qwen API)"
                    add_event("Log Analyzer", f"Produced {len(hypotheses)} hypotheses (Qwen API)")
                    return
            except (json.JSONDecodeError, KeyError):
                pass

    # No fallback - analysis requires Qwen API
    agent["status"] = "done"
    agent["message"] = "Analysis unavailable - Qwen API required"
    agent["findings"] = [{"cause": "Analysis unavailable", "confidence": 0, "evidence": ["Qwen API not available or response parsing failed"], "severity": "unknown"}]
    add_event("Log Analyzer", "Analysis unavailable - Qwen API required")


def run_metric_monitor(metrics_data):
    agent = state["agents"]["metric_monitor"]
    agent["status"] = "running"
    agent["message"] = f"Analyzing {len(metrics_data)} metric snapshots..."
    add_event("Metric Monitor", f"Analyzing {len(metrics_data)} metric snapshots from incident window")

    if QWEN_AVAILABLE and metrics_data:
        agent["message"] = "Calling Qwen API..."
        add_event("Metric Monitor", "Analyzing metrics with Qwen Cloud API")
        raw = _call_qwen(METRIC_MONITOR_PROMPT, f"Analyze these metrics:\n\n{json.dumps(metrics_data, indent=2)}")
        if raw:
            try:
                hypotheses = _parse_json(raw)
                if isinstance(hypotheses, list) and hypotheses:
                    # Use the model's own hypotheses + evidence verbatim (authentic output).
                    agent["findings"] = hypotheses
                    agent["status"] = "done"
                    agent["message"] = f"Produced {len(hypotheses)} hypotheses (Qwen API)"
                    add_event("Metric Monitor", f"Produced {len(hypotheses)} hypotheses (Qwen API)")
                    return
            except (json.JSONDecodeError, KeyError):
                pass

    # No fallback - analysis requires Qwen API
    agent["status"] = "done"
    agent["message"] = "Analysis unavailable - Qwen API required"
    agent["findings"] = [{"cause": "Analysis unavailable", "confidence": 0, "evidence": ["Qwen API not available or response parsing failed"], "severity": "unknown"}]
    add_event("Metric Monitor", "Analysis unavailable - Qwen API required")


def run_coordinator(log_hyps, met_hyps):
    agent = state["agents"]["coordinator"]
    agent["status"] = "running"
    agent["message"] = "Arbitrating between agent hypotheses..."
    add_event("Coordinator", "Arbitrating between Log Analyzer and Metric Monitor")

    if QWEN_AVAILABLE:
        agent["message"] = "Calling Qwen API..."
        add_event("Coordinator", "Running arbitration with Qwen Cloud API")
        user_input = (
            f"Log Analyzer hypotheses:\n{json.dumps(log_hyps, indent=2)}\n\n"
            f"Metric Monitor hypotheses:\n{json.dumps(met_hyps, indent=2)}\n\n"
            f"Compare evidence and determine root cause."
        )
        raw = _call_qwen(COORDINATOR_PROMPT, user_input)
        if raw:
            try:
                result = _parse_json(raw)
                if isinstance(result, dict) and "root_cause" in result:
                    state["root_cause"] = result["root_cause"]
                    state["action_plan"] = result.get("action_plan", {})
                    agent["findings"] = [result["root_cause"]]
                    agent["status"] = "done"
                    agent["message"] = f"Root cause determined (Qwen API)"
                    add_event("Coordinator", f"Root cause determined (Qwen API)")
                    return
            except (json.JSONDecodeError, KeyError):
                pass

    # No fallback - analysis requires Qwen API
    agent["status"] = "done"
    agent["message"] = "Analysis unavailable - Qwen API required"
    state["root_cause"] = {"cause": "Analysis unavailable", "confidence": 0, "severity": "unknown"}
    state["action_plan"] = {"steps": []}
    add_event("Coordinator", "Analysis unavailable - Qwen API required")


def run_remediation(action_plan):
    agent = state["agents"]["runbook_executor"]
    agent["status"] = "running"
    steps = action_plan.get("steps", [])
    agent["message"] = f"Executing {len(steps)} remediation steps..."
    add_event("Runbook Executor", f"Executing {len(steps)} remediation steps")

    if QWEN_AVAILABLE and steps:
        agent["message"] = "Calling Qwen API..."
        add_event("Runbook Executor", "Simulating execution with Qwen Cloud API")
        user_input = f"Simulate executing these remediation steps and report results:\n\n" + "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps))
        raw = _call_qwen("You are an operations engineer executing remediation steps. Report success/failure for each step.", user_input)
        if raw:
            agent["status"] = "done"
            agent["message"] = f"All {len(steps)} steps completed (Qwen API)"
            add_event("Runbook Executor", f"All {len(steps)} steps completed (Qwen API)")
            return

    # No fallback - requires Qwen API
    agent["status"] = "done"
    agent["message"] = "Analysis unavailable - Qwen API required"
    add_event("Runbook Executor", "Analysis unavailable - Qwen API required")


def run_postmortem():
    agent = state["agents"]["postmortem_writer"]
    agent["status"] = "running"
    agent["message"] = "Generating incident report..."
    add_event("Post-Mortem Writer", "Generating comprehensive incident report")

    if QWEN_AVAILABLE:
        # Build comprehensive context from actual data
        transcript = "\n".join(f"[{e['time']}] {e['agent']}: {e['message']}" for e in state["events"])
        
        # Add actual metrics data
        metrics_summary = ""
        if state["peak_metrics"]:
            pm = state["peak_metrics"]
            metrics_summary = f"""
INCIDENT METRICS (Peak Values):
- Error Rate: {pm.get('error_rate', 0):.1f}%
- CPU Usage: {pm.get('cpu_pct', 0):.1f}%
- Memory: {pm.get('memory_mb', 0):.0f} MB
- P50 Latency: {pm.get('p50_latency_ms', 0):.0f} ms
- P95 Latency: {pm.get('p95_latency_ms', 0):.0f} ms
- P99 Latency: {pm.get('p99_latency_ms', 0):.0f} ms
- Total Requests: {pm.get('request_count', 0)}
- Queue Errors: {pm.get('queue_errors', 0)}
- Cache Hit Rate: {pm.get('cache_hit_rate', 0):.0f}%
"""

        # Add agent findings
        findings_summary = ""
        for agent_name in ["log_analyzer", "metric_monitor", "coordinator"]:
            agent_data = state["agents"].get(agent_name, {})
            if agent_data.get("findings"):
                findings_summary += f"\n{agent_name.upper()} FINDINGS:\n"
                for f in agent_data["findings"]:
                    findings_summary += f"- Cause: {f.get('cause', 'Unknown')}\n"
                    findings_summary += f"  Confidence: {int(f.get('confidence', 0) * 100)}%\n"
                    if f.get("evidence"):
                        findings_summary += f"  Evidence: {', '.join(f['evidence'])}\n"
                    if f.get("code_location"):
                        loc = f["code_location"]
                        findings_summary += f"  Code: {loc.get('file')}:{loc.get('line')} ({loc.get('function')})\n"

        # Add root cause and action plan
        root_cause_summary = ""
        if state.get("root_cause"):
            rc = state["root_cause"]
            root_cause_summary = f"""
ROOT CAUSE DETERMINED:
- Cause: {rc.get('cause', 'Unknown')}
- Confidence: {int(rc.get('confidence', 0) * 100)}%
- Severity: {rc.get('severity', 'unknown').upper()}
"""

        action_plan_summary = ""
        if state.get("action_plan", {}).get("steps"):
            action_plan_summary = "\nACTION PLAN:\n"
            for i, step in enumerate(state["action_plan"]["steps"], 1):
                action_plan_summary += f"{i}. {step}\n"

        today = datetime.now().strftime("%Y-%m-%d")
        window = f"{state.get('incident_start', '?')} to {state.get('incident_end', '?')}"

        prompt = f"""Generate a comprehensive incident post-mortem report based on the ACTUAL data below.

REPORT FACTS (use these verbatim — do NOT invent alternatives):
- Date: {today}
- Detection-to-resolution window: {window}
- Prepared by: ResQ Autonomous Incident Response System

INCIDENT TIMELINE:
{transcript}

{metrics_summary}
{findings_summary}
{root_cause_summary}
{action_plan_summary}

Write a professional post-mortem with:
1. Executive Summary
2. Incident Timeline (with actual timestamps)
3. Root Cause Analysis (based on actual findings)
4. Impact Assessment (use actual metric values)
5. Resolution (what was actually done)
6. Action Items (based on the actual action plan)
7. Lessons Learned

Be specific and reference actual data points."""

        raw = _call_qwen(
            "You are a technical writer creating an incident post-mortem. Use ONLY the actual data "
            "provided. Do NOT fabricate any of the following: incident ID numbers (e.g. 'RESQ-2024-###'), "
            "calendar dates, author names, or exact source-file paths and line numbers. Use the Date given "
            "in REPORT FACTS; if a value is not provided, omit it rather than inventing one. Only cite a "
            "specific file/line if it appears verbatim in the provided timeline or findings.",
            prompt
        )
        if raw:
            state["postmortem"] = raw
            agent["status"] = "done"
            agent["message"] = "Report generated (Qwen API)"
            add_event("Post-Mortem Writer", "Report generated (Qwen API)")
            return

    # No fallback - requires Qwen API
    agent["status"] = "done"
    agent["message"] = "Analysis unavailable - Qwen API required"
    state["postmortem"] = "Post-mortem generation requires Qwen API."
    add_event("Post-Mortem Writer", "Analysis unavailable - Qwen API required")


def store_report_to_oss():
    """Phase 5 — persist ResQ's own investigation to Alibaba OSS.

    Closes the loop: the post-mortem the swarm just produced is POSTed to the
    monitored service's /api/reports endpoint, which writes it to OSS. This turns
    the investigation into a real, retrievable artifact instead of ephemeral TUI
    output. Best-effort — a storage failure never blocks incident resolution.
    """
    agent = state["agents"]["postmortem_writer"]
    rc = state.get("root_cause") or {}
    negotiation = state.get("negotiation") or {}
    incident_id = f"incident-{datetime.now().strftime('%Y%m%dT%H%M%S')}"

    report = {
        "id": incident_id,
        "summary": rc.get("cause", "Incident investigated by ResQ"),
        "severity": rc.get("severity", "unknown"),
        "confidence": rc.get("confidence", 0),
        "root_cause": rc,
        "action_plan": state.get("action_plan", {}),
        "peak_metrics": state.get("peak_metrics", {}),
        "negotiation": {
            "disagreement": negotiation.get("disagreement"),
            "resolved": negotiation.get("resolved"),
            "log_before": negotiation.get("log_before"),
            "log_after": negotiation.get("log_after"),
            "metric_before": negotiation.get("metric_before"),
            "metric_after": negotiation.get("metric_after"),
        },
        "postmortem": state.get("postmortem", ""),
        "detected_at": state.get("incident_start"),
        "resolved_at": state.get("incident_end"),
        "investigated_by": "ResQ multi-agent swarm (5 agents, Qwen Cloud)",
    }

    add_event("Post-Mortem Writer", "Persisting incident report to Alibaba OSS...")
    try:
        resp = requests.post(f"{TARGET_URL}/api/reports", json=report, timeout=10)
        resp.raise_for_status()
        oss_key = resp.json().get("oss_key", "")
        state["oss_report_key"] = oss_key
        agent["message"] = f"Report stored to OSS: {oss_key}"
        add_event("Post-Mortem Writer", f"Report persisted to Alibaba OSS -> {oss_key}")
    except Exception as e:  # noqa: BLE001 - storage is best-effort, never fatal
        state["oss_report_key"] = None
        agent["message"] = "Report generated (OSS storage unavailable)"
        add_event("Post-Mortem Writer", f"OSS storage failed: {e}")


def _top_cause(findings):
    """Highest-confidence hypothesis cause from a findings list."""
    if not findings:
        return ""
    return (max(findings, key=lambda h: h.get("confidence", 0)).get("cause", "") or "")


def _negotiate_agent(agent_prompt, own_hyps, peer_name, peer_hyps):
    """Ask one agent to reconsider its hypotheses given a peer's. Returns revised or None."""
    if not (QWEN_AVAILABLE and peer_hyps):
        return None
    user_input = (
        f"YOUR CURRENT HYPOTHESES:\n{json.dumps(own_hyps, indent=2)}\n\n"
        f"PEER ({peer_name}) HYPOTHESES:\n{json.dumps(peer_hyps, indent=2)}\n\n"
        f"Re-examine all of the above together and return your revised hypotheses."
    )
    raw = _call_qwen(agent_prompt + NEGOTIATION_SUFFIX, user_input)
    if not raw:
        return None
    try:
        revised = _parse_json(raw)
        if isinstance(revised, list) and revised:
            return revised
    except (json.JSONDecodeError, KeyError):
        pass
    return None


def _detect_disagreement(cause_a, cause_b):
    """True if the two top causes name DIFFERENT root causes.

    Uses the model to judge semantic conflict (a symptom is not its cause), which
    is far more reliable than word overlap — the old keyword heuristic wrongly read
    'memory leak' and 'cache failure' as agreement because both mention 'requests'/
    'query'. Falls back to the hardened keyword heuristic if Qwen is unavailable.
    """
    if not (cause_a and cause_b):
        return False
    if QWEN_AVAILABLE:
        raw = _call_qwen(
            CONFLICT_CHECK_SYSTEM,
            f"Hypothesis A: {cause_a}\n\nHypothesis B: {cause_b}\n\n"
            "Do these identify the SAME root cause or DIFFERENT ones? Answer SAME or DIFFERENT.",
        )
        if raw:
            ans = raw.strip().upper()
            if ans.startswith("DIFFERENT"):
                return True
            if ans.startswith("SAME"):
                return False
    return not causes_agree(cause_a, cause_b)


def run_negotiation():
    """Phase 1.5 — agents exchange hypotheses and reconcile disagreements.

    This is the 'dialogue and negotiation' step: when the Log Analyzer and Metric
    Monitor disagree, each re-examines the incident with the other's evidence.
    """
    log_agent = state["agents"]["log_analyzer"]
    met_agent = state["agents"]["metric_monitor"]
    neg = state["negotiation"]
    neg["status"] = "running"

    log_before = _top_cause(log_agent["findings"])
    met_before = _top_cause(met_agent["findings"])
    neg["log_before"], neg["metric_before"] = log_before, met_before

    disagreement = _detect_disagreement(log_before, met_before)
    neg["disagreement"] = disagreement

    if not disagreement:
        neg["status"] = "done"
        neg["resolved"] = "agreement"
        add_event("System", "Agents agree on the root cause — no negotiation needed")
        return

    add_event("System", "Agents disagree — opening negotiation round")
    add_event("Log Analyzer", f"Position: {log_before[:70]}")
    add_event("Metric Monitor", f"Position: {met_before[:70]}")

    add_event("Log Analyzer", "Reconsidering with Metric Monitor's evidence...")
    add_event("Metric Monitor", "Reconsidering with Log Analyzer's evidence...")
    revised_log = _negotiate_agent(LOG_ANALYZER_PROMPT, log_agent["findings"],
                                   "metric_monitor", met_agent["findings"])
    revised_met = _negotiate_agent(METRIC_MONITOR_PROMPT, met_agent["findings"],
                                   "log_analyzer", log_agent["findings"])

    if revised_log:
        # Re-read source code for any revised hypotheses that cite a location.
        for h in revised_log:
            loc = h.get("code_location")
            if loc and loc.get("file") and loc.get("line"):
                src = _read_source_code(loc["file"], loc["line"],
                                        function=loc.get("function"))
                if src:
                    h["source_code"] = src
        log_agent["findings"] = revised_log
    if revised_met:
        met_agent["findings"] = revised_met

    log_after = _top_cause(log_agent["findings"])
    met_after = _top_cause(met_agent["findings"])
    neg["log_after"], neg["metric_after"] = log_after, met_after

    if log_after and log_after != log_before:
        add_event("Log Analyzer", f"Revised position: {log_after[:70]}")
    if met_after and met_after != met_before:
        add_event("Metric Monitor", f"Revised position: {met_after[:70]}")

    neg["resolved"] = "revised"
    neg["status"] = "done"
    add_event("System", "Negotiation complete — Coordinator will arbitrate revised findings")


def run_investigation(logs_snapshot, metrics_snapshot):
    state["status"] = "investigating"
    add_event("System", "Incident detected — deploying ResQ agent swarm")

    add_event("System", "Phase 1: Parallel diagnosis")
    log_thread = threading.Thread(target=run_log_analyzer, args=(logs_snapshot,))
    metric_thread = threading.Thread(target=run_metric_monitor, args=(metrics_snapshot,))
    log_thread.start()
    metric_thread.start()
    log_thread.join()
    metric_thread.join()

    add_event("System", "Phase 1.5: Inter-agent negotiation")
    run_negotiation()

    add_event("System", "Phase 2: Coordinator arbitration")
    run_coordinator(
        state["agents"]["log_analyzer"]["findings"],
        state["agents"]["metric_monitor"]["findings"],
    )

    add_event("System", "Phase 3: Runbook execution")
    run_remediation(state["action_plan"] or {})

    add_event("System", "Phase 4: Post-mortem generation")
    run_postmortem()

    state["incident_end"] = datetime.now().strftime("%H:%M:%S")

    add_event("System", "Phase 5: Persisting report to Alibaba OSS")
    store_report_to_oss()

    state["status"] = "resolved"
    add_event("System", "Incident resolved — all agents complete")


# ── Textual Widgets ──────────────────────────────────────────────────
class MetricsWidget(Static):
    """Displays service metrics."""

    def on_mount(self):
        self.border_title = "Service Metrics"
        self.set_interval(1.0, self.refresh_metrics)

    def refresh_metrics(self):
        # After resolution, show peak incident metrics as evidence
        if state["status"] == "resolved" and state["peak_metrics"]:
            pm = state["peak_metrics"]
            err = pm.get("error_rate", 0)
            err_c = "red" if err > 10 else "yellow" if err > 5 else "green"
            cpu = pm.get("cpu_pct", 0)
            cpu_c = "red" if cpu > 80 else "yellow" if cpu > 50 else "green"
            mem = pm.get("memory_mb", 0)
            mem_c = "yellow" if mem > 500 else "green"
            p50 = pm.get("p50_latency_ms", 0)
            p95 = pm.get("p95_latency_ms", 0)
            p95_c = "red" if p95 > 2000 else "yellow" if p95 > 500 else "green"
            p99 = pm.get("p99_latency_ms", 0)
            p99_c = "red" if p99 > 5000 else "yellow" if p99 > 1000 else "green"
            req = pm.get("request_count", 0)

            lines = [
                "[bold]Incident Peak Metrics (Evidence):[/bold]",
                "",
                f"[bold]Error Rate:[/bold]      [{err_c}]{err:.1f}%[/{err_c}]",
                f"[bold]CPU Usage:[/bold]       [{cpu_c}]{cpu:.1f}%[/{cpu_c}]",
                f"[bold]Memory (RSS):[/bold]    [{mem_c}]{mem:.0f} MB[/{mem_c}]",
                f"[bold]Cache Hit Rate:[/bold]  {pm.get('cache_hit_rate', 0):.0f}%",
                f"[bold]Queue Status:[/bold]    {'OK' if pm.get('queue_healthy', True) else 'FAILED'}",
                f"[bold]Queue Errors:[/bold]    {pm.get('queue_errors', 0)}",
                f"[bold]P50 Latency:[/bold]     {p50:.0f} ms",
                f"[bold]P95 Latency:[/bold]     [{p95_c}]{p95:.0f} ms[/{p95_c}]",
                f"[bold]P99 Latency:[/bold]     [{p99_c}]{p99:.0f} ms[/{p99_c}]",
                f"[bold]Total Requests:[/bold]  {req} (during incident window)",
            ]
            self.update("\n".join(lines))
            self.border_title = "Service Metrics — Incident Evidence"
            return

        m = state["metrics"]
        if not m:
            self.update("[dim]Waiting for metrics...[/dim]")
            return

        err = m.get("error_rate", 0)
        err_c = "red" if err > 10 else "yellow" if err > 5 else "green"
        cpu = m.get("cpu_pct", 0)
        cpu_c = "red" if cpu > 80 else "yellow" if cpu > 50 else "green"
        mem = m.get("memory_mb", 0)
        p50 = m.get("p50_latency_ms", 0)
        p95 = m.get("p95_latency_ms", 0)
        p99 = m.get("p99_latency_ms", 0)
        req = m.get("request_count", 0)

        lines = [
            f"[bold]Error Rate:[/bold]  [{err_c}]{err:.1f}%[/{err_c}]",
            f"[bold]CPU:[/bold]         [{cpu_c}]{cpu:.1f}%[/{cpu_c}]",
            f"[bold]Memory:[/bold]      [purple]{mem:.0f} MB[/purple]",
            f"[bold]P50 Latency:[/bold] {p50:.0f} ms",
            f"[bold]P95 Latency:[/bold] [yellow]{p95:.0f} ms[/yellow]" if p95 > 500 else f"[bold]P95 Latency:[/bold] {p95:.0f} ms",
            f"[bold]P99 Latency:[/bold] [red]{p99:.0f} ms[/red]" if p99 > 1000 else f"[bold]P99 Latency:[/bold] {p99:.0f} ms",
            f"[bold]Requests:[/bold]    {req}",
        ]
        self.update("\n".join(lines))


class AgentsWidget(Static):
    """Displays agent status and findings."""
    can_focus = True

    def on_mount(self):
        self.border_title = "Agent Investigation"
        self.set_interval(0.5, self.refresh_agents)

    def refresh_agents(self):
        agent_order = [
            ("log_analyzer", "Log Analyzer"),
            ("metric_monitor", "Metric Monitor"),
            ("coordinator", "Coordinator"),
            ("runbook_executor", "Runbook Executor"),
            ("postmortem_writer", "Post-Mortem Writer"),
        ]

        lines = []
        for key, name in agent_order:
            agent = state["agents"][key]
            status = agent["status"]
            color = AGENT_COLORS.get(name, "white")
            icon = AGENT_ICONS.get(name, "●")

            if status == "idle":
                icon_status = "[dim]●[/dim]"
            elif status == "running":
                icon_status = f"[{color}]◉[/{color}]"
            else:
                icon_status = "[green]✓[/green]"

            lines.append(f"{icon_status} [{color}]{icon} {name}[/{color}]  [dim]{agent['message']}[/dim]")

            if agent["findings"] and status == "done":
                for f in agent["findings"]:
                    cause = f.get("cause", "Unknown")
                    conf = int(f.get("confidence", 0) * 100)
                    conf_c = "red" if conf > 80 else "yellow" if conf > 60 else "green"
                    lines.append(f"    [bold]{cause}[/bold]")
                    lines.append(f"    [dim]Confidence:[/dim] [{conf_c}]{conf}%[/{conf_c}]")

                    # Show code location if available
                    code_loc = f.get("code_location")
                    if code_loc:
                        loc_str = f"{code_loc.get('file', '?')}:{code_loc.get('line', '?')}"
                        func = code_loc.get('function', '')
                        lines.append(f"    [bold yellow]Code:[/bold yellow] {loc_str} ({func})")

                    # Show source code snippet if available
                    source = f.get("source_code")
                    if source:
                        lines.append(f"    [dim]Source:[/dim]")
                        for src_line in source.split("\n"):
                            lines.append(f"    [dim]{src_line}[/dim]")

                    # Show stack traces if available
                    stacks = f.get("stack_traces", [])
                    if stacks:
                        lines.append(f"    [bold red]Stack Trace:[/bold red]")
                        for stack in stacks:
                            for st_line in stack.split("\n"):
                                lines.append(f"    [red]{st_line}[/red]")

                    # Show analysis/explanation if available
                    analysis = f.get("analysis")
                    if analysis:
                        lines.append(f"    [bold cyan]Analysis:[/bold cyan]")
                        # Word wrap the analysis
                        words = analysis.split()
                        current_line = ""
                        for word in words:
                            if len(current_line) + len(word) + 1 > 65:
                                lines.append(f"    [cyan]{current_line}[/cyan]")
                                current_line = word
                            else:
                                current_line = f"{current_line} {word}" if current_line else word
                        if current_line:
                            lines.append(f"    [cyan]{current_line}[/cyan]")

                    for ev in f.get("evidence", []):
                        lines.append(f"    [dim]  • {ev}[/dim]")
            lines.append("")

        self.update("\n".join(lines))


class NegotiationWidget(Static):
    """Displays the inter-agent negotiation (conflict detection + resolution)."""
    can_focus = True

    def on_mount(self):
        self.border_title = "Agent Negotiation"
        self._scrolled_into_view = False
        self.set_interval(0.5, self.refresh_neg)

    def refresh_neg(self):
        neg = state["negotiation"]
        if neg["status"] == "idle":
            self.update("[dim]Awaiting parallel diagnosis...[/dim]")
            return

        # Bring this panel into view once, the moment the negotiation becomes
        # active, so it isn't left below the fold during the run (it sits 4th in
        # the scroll column). One-shot so it never fights manual scrolling.
        if not self._scrolled_into_view and neg["status"] != "idle":
            self._scrolled_into_view = True
            try:
                self.scroll_visible(animate=True, top=True)
            except Exception:
                pass

        if neg.get("disagreement") is False:
            self.update("[green]✓ Log Analyzer and Metric Monitor agree — "
                        "no conflict to resolve.[/green]")
            return

        lines = ["[bold red]⚔ Conflict detected between specialists[/bold red]", ""]
        lines.append("[dim]Initial positions:[/dim]")
        lines.append(f"  [blue]📝 Log Analyzer:[/blue]\n    {neg.get('log_before', '')}")
        lines.append(f"  [magenta]📊 Metric Monitor:[/magenta]\n    {neg.get('metric_before', '')}")

        if neg["status"] == "running":
            lines.append("")
            lines.append("[yellow]↔ Agents exchanging evidence and reconsidering...[/yellow]")
        elif neg["status"] == "done":
            lines.append("")
            lines.append("[dim]After negotiation:[/dim]")
            la = neg.get("log_after") or "(unchanged)"
            ma = neg.get("metric_after") or "(unchanged)"
            lines.append(f"  [blue]📝 Log Analyzer:[/blue]\n    {la}")
            lines.append(f"  [magenta]📊 Metric Monitor:[/magenta]\n    {ma}")
            lines.append("")
            lines.append("[green]✓ Conflict resolved — revised findings sent to Coordinator[/green]")

        self.update("\n".join(lines))


class TimelineWidget(RichLog):
    """Displays event timeline using RichLog for proper scrolling."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs, highlight=True, markup=True, auto_scroll=False)
        self.can_focus = True

    def on_mount(self):
        self.border_title = "Event Timeline"
        self.set_interval(0.5, self.refresh_timeline)
        self._last_count = 0

    def refresh_timeline(self):
        events = state["events"]
        if len(events) == self._last_count:
            return

        for e in events[self._last_count:]:
            color = AGENT_COLORS.get(e["agent"], "white")
            self.write(f"[dim]{e['time']}[/dim] [bold {color}]{e['agent']}[/bold {color}] {e['message']}")
        self._last_count = len(events)


class RootCauseWidget(Static):
    """Displays root cause and action plan."""
    can_focus = True

    def on_mount(self):
        self.border_title = "Root Cause & Action Plan"
        self.set_interval(1.0, self.refresh_rc)

    def refresh_rc(self):
        rc = state.get("root_cause")
        if not rc:
            self.update("[dim]Waiting for investigation...[/dim]")
            return

        conf = int(rc.get("confidence", 0) * 100)
        lines = [
            f"[bold green]{rc.get('cause', 'Unknown')}[/bold green]",
            f"[dim]Confidence: {conf}%  |  Severity: {rc.get('severity', 'unknown').upper()}[/dim]",
        ]

        # Add incident timeline
        start = state.get("incident_start", "")
        end = state.get("incident_end", "")
        if start and end:
            lines.append(f"[dim]Incident: {start} → {end}[/dim]")
        lines.append("")

        ap = state.get("action_plan", {})
        if ap.get("steps"):
            lines.append("[bold yellow]Action Plan:[/bold yellow]")
            for i, step in enumerate(ap["steps"]):
                lines.append(f"  {i+1}. {step}")

        pm = state.get("postmortem")
        if pm:
            lines.append("")
            lines.append("[bold cyan]Post-Mortem:[/bold cyan]")
            lines.append(f"[dim]{pm}[/dim]")

        self.update("\n".join(lines))


class StatusBar(Static):
    """Displays status bar."""

    def on_mount(self):
        self.set_interval(0.5, self.refresh_status)

    def refresh_status(self):
        s = state["status"]
        colors = {"monitoring": "green", "incident": "red", "investigating": "yellow", "resolved": "green"}
        labels = {"monitoring": "MONITORING", "incident": "INCIDENT DETECTED", "investigating": "INVESTIGATING", "resolved": "RESOLVED"}
        color = colors.get(s, "white")
        label = labels.get(s, "UNKNOWN")

        text = f" [bold cyan]ResQ[/bold cyan] Multi-Agent Incident Response  [dim]|[/dim]  [bold white on {color}] {label} [/bold white on {color}]"
        if state.get("incident_start"):
            text += f"  [dim]|  Started {state['incident_start']}[/dim]"
        if state.get("incident_end"):
            text += f"  [dim]|  Ended {state['incident_end']}[/dim]"
        if s == "resolved":
            text += "  [dim]|  Press q to quit[/dim]"
        self.update(text)


# ── Textual App ──────────────────────────────────────────────────────
class ResQApp(App):
    CSS = """
    Screen {
        background: $surface;
    }
    #main-scroll {
        height: 1fr;
        overflow-y: auto;
    }
    #status-bar {
        dock: top;
        height: 1;
        background: $surface;
        padding: 0 1;
    }
    .widget {
        margin: 0 1 1 1;
        padding: 0 1;
        height: auto;
    }
    #metrics-panel {
        border: solid $success;
    }
    #rootcause-panel {
        border: solid $success;
    }
    #agents-panel {
        border: solid $warning;
    }
    #negotiation-panel {
        border: solid $error;
    }
    #timeline-panel {
        border: solid $accent;
        scrollbar-size: 0 0;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("up", "scroll_up", "Scroll Up"),
        ("down", "scroll_down", "Scroll Down"),
        ("pageup", "scroll_page_up", "Page Up"),
        ("pagedown", "scroll_page_down", "Page Down"),
    ]

    def action_scroll_up(self):
        self.query_one("#main-scroll").scroll_up()

    def action_scroll_down(self):
        self.query_one("#main-scroll").scroll_down()

    def action_scroll_page_up(self):
        self.query_one("#main-scroll").scroll_page_up()

    def action_scroll_page_down(self):
        self.query_one("#main-scroll").scroll_page_down()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield StatusBar(id="status-bar")
        with VerticalScroll(id="main-scroll"):
            yield MetricsWidget(id="metrics-panel", classes="widget")
            yield RootCauseWidget(id="rootcause-panel", classes="widget")
            yield AgentsWidget(id="agents-panel", classes="widget")
            yield NegotiationWidget(id="negotiation-panel", classes="widget")
            yield TimelineWidget(id="timeline-panel", classes="widget")
        yield Footer()

    def on_mount(self):
        # Start metrics polling
        threading.Thread(target=self._poll_metrics, daemon=True).start()
        time.sleep(1)
        # Start anomaly detection
        threading.Thread(target=self._detect_loop, daemon=True).start()

    def _poll_metrics(self):
        while True:
            try:
                r = requests.get(f"{TARGET_URL}/api/metrics", timeout=3)
                if r.status_code == 200:
                    m = r.json()
                    state["metrics"] = m
                    state["metrics_history"].append(m)
                    if len(state["metrics_history"]) > 120:
                        state["metrics_history"].pop(0)
                    # Track peak metrics during incident
                    if state["status"] in ("incident", "investigating"):
                        pm = state["peak_metrics"]
                        for key in ("error_rate", "cpu_pct", "memory_mb", "p50_latency_ms", "p95_latency_ms", "p99_latency_ms", "request_count", "queue_errors"):
                            val = m.get(key, 0)
                            if val > pm.get(key, 0):
                                pm[key] = val
            except Exception:
                pass
            time.sleep(1.5)

    def _detect_loop(self):
        investigation_started = False
        while True:
            if investigation_started:
                time.sleep(1)
                continue

            m = state["metrics"]
            if m.get("error_rate", 0) > 8 or m.get("p99_latency_ms", 0) > 1500:
                investigation_started = True
                state["status"] = "incident"
                state["incident_time"] = datetime.now().strftime("%H:%M:%S")
                state["incident_start"] = datetime.now().strftime("%H:%M:%S")

                # Capture snapshots
                try:
                    logs_r = requests.get(f"{TARGET_URL}/api/logs", timeout=5)
                    logs_snapshot = logs_r.json().get("logs", [])
                except Exception:
                    logs_snapshot = []
                metrics_snapshot = list(state["metrics_history"])

                # Run investigation
                def do_investigate():
                    run_investigation(logs_snapshot, metrics_snapshot)
                threading.Thread(target=do_investigate, daemon=True).start()

            time.sleep(1)


def main():
    app = ResQApp()
    app.run()


if __name__ == "__main__":
    main()
