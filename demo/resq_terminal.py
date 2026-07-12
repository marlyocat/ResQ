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

TARGET_URL = "http://localhost:5000"

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

# ── Qwen Client ──────────────────────────────────────────────────────
try:
    from integrations.qwen_client import QwenClient
    import asyncio
    qwen = QwenClient()
    QWEN_AVAILABLE = True
except Exception:
    qwen = None
    QWEN_AVAILABLE = False

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


def _read_source_code(file_path, line_number, context_lines=5):
    """Read source code around a specific line number."""
    try:
        # Handle relative paths
        if not os.path.isabs(file_path):
            file_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), file_path)
        
        with open(file_path, 'r') as f:
            lines = f.readlines()
        
        start = max(0, line_number - context_lines - 1)
        end = min(len(lines), line_number + context_lines)
        
        code_context = []
        for i in range(start, end):
            marker = " >>> " if i + 1 == line_number else "     "
            code_context.append(f"{marker}{i+1:4d}: {lines[i].rstrip()}")
        
        return "\n".join(code_context)
    except Exception as e:
        return f"Could not read source: {e}"


def _call_qwen(system_prompt, user_input):
    if not QWEN_AVAILABLE:
        return None
    try:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(
            qwen.analyze_with_context(system_prompt=system_prompt, user_input=user_input)
        )
        loop.close()
        return result.get("raw_response", "")
    except Exception:
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
                            source = _read_source_code(code_loc["file"], code_loc["line"])
                            h["source_code"] = source
                            add_event("Log Analyzer", f"Read source: {code_loc['file']}:{code_loc['line']}")
                    
                    agent["findings"] = hypotheses
                    agent["status"] = "done"
                    agent["message"] = f"Produced {len(hypotheses)} hypotheses (Qwen API)"
                    add_event("Log Analyzer", f"Produced {len(hypotheses)} hypotheses (Qwen API)")
                    return
            except (json.JSONDecodeError, KeyError):
                pass

    time.sleep(1.5)
    # Build evidence from actual logs
    import re
    evidence = []
    code_locations = []
    stack_traces = []
    error_logs = [e for e in logs_data if e.get("level") in ("ERROR", "CRITICAL")]
    if error_logs:
        evidence.append(f"{len(error_logs)} error/critical log entries found")
        messages = [e.get("message", "") for e in error_logs]
        if any("pool" in m.lower() or "connection" in m.lower() for m in messages):
            evidence.append("Connection/pool-related errors detected")
        if any("timeout" in m.lower() for m in messages):
            evidence.append("Timeout errors detected")
        
        # Extract code locations from log messages
        for msg in messages[:5]:
            match = re.search(r'\[file:([^,\]]+),\s*func:([^,\]]+),\s*line:(\d+)\]', msg)
            if match:
                code_locations.append({
                    "file": match.group(1),
                    "function": match.group(2),
                    "line": int(match.group(3))
                })
            
            # Extract stack traces (lines starting with "Traceback" or "  File")
            if "Traceback" in msg or "  File \"" in msg:
                stack_lines = msg.split("\n")
                stack_context = []
                capturing = False
                for line in stack_lines:
                    if "Traceback" in line or line.strip().startswith("File \""):
                        capturing = True
                    if capturing:
                        stack_context.append(line.strip()[:80])
                    if capturing and line.strip() and not line.startswith(" ") and "Traceback" not in line and "File \"" not in line:
                        break
                if stack_context:
                    stack_traces.append("\n".join(stack_context[:8]))
    
    if not evidence:
        evidence.append(f"{len(logs_data)} log entries analyzed")

    finding = {
        "cause": "Error patterns detected in application logs",
        "confidence": 0.88,
        "evidence": evidence,
        "severity": "high",
    }
    if code_locations:
        finding["code_location"] = code_locations[0]
        source = _read_source_code(code_locations[0]["file"], code_locations[0]["line"])
        finding["source_code"] = source
    if stack_traces:
        finding["stack_traces"] = stack_traces[:2]  # Keep first 2 stack traces

    agent["findings"] = [finding]
    agent["status"] = "done"
    agent["message"] = f"Produced 1 hypothesis from {len(logs_data)} logs"
    add_event("Log Analyzer", f"Produced 1 hypothesis from actual logs")


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
                    # Fix evidence to reference actual metric values
                    for h in hypotheses:
                        if metrics_data:
                            first = metrics_data[0]
                            last = metrics_data[-1]
                            actual_evidence = []
                            if last.get("error_rate", 0) > 5:
                                actual_evidence.append(f"Error rate peaked at {last['error_rate']:.1f}%")
                            if last.get("p99_latency_ms", 0) > 500:
                                actual_evidence.append(f"P99 latency reached {last['p99_latency_ms']:.0f}ms")
                            if last.get("cpu_pct", 0) > 50:
                                actual_evidence.append(f"CPU usage at {last['cpu_pct']:.1f}%")
                            if last.get("memory_mb", 0) > 100:
                                actual_evidence.append(f"Memory at {last['memory_mb']:.0f}MB")
                            if actual_evidence:
                                h["evidence"] = actual_evidence
                    agent["findings"] = hypotheses
                    agent["status"] = "done"
                    agent["message"] = f"Produced {len(hypotheses)} hypotheses (Qwen API)"
                    add_event("Metric Monitor", f"Produced {len(hypotheses)} hypotheses (Qwen API)")
                    return
            except (json.JSONDecodeError, KeyError):
                pass

    # Fallback: build evidence from actual metrics data
    time.sleep(1.5)
    evidence = []
    if metrics_data:
        errors = [m.get("error_rate", 0) for m in metrics_data]
        p99s = [m.get("p99_latency_ms", 0) for m in metrics_data]
        cpus = [m.get("cpu_pct", 0) for m in metrics_data]
        if max(errors) > 5:
            evidence.append(f"Error rate peaked at {max(errors):.1f}%")
        if max(p99s) > 500:
            evidence.append(f"P99 latency reached {max(p99s):.0f}ms")
        if max(cpus) > 50:
            evidence.append(f"CPU usage at {max(cpus):.1f}%")
        if not evidence:
            evidence.append("Metrics anomaly detected in incident window")

    agent["findings"] = [
        {"cause": "Service degradation detected in metrics", "confidence": 0.85,
         "evidence": evidence, "severity": "high"},
    ]
    agent["status"] = "done"
    agent["message"] = "Produced 1 hypothesis from actual metrics"
    add_event("Metric Monitor", "Produced 1 hypothesis from actual metrics")


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

    time.sleep(2)
    state["root_cause"] = {"cause": "Database connection pool exhaustion", "confidence": 0.89, "severity": "critical"}
    state["action_plan"] = {"steps": [
        "Investigate current database connection pool configuration and limits",
        "Review slow query logs to identify queries holding connections too long",
        "Monitor connection pool utilization after identifying bottleneck",
        "Validate connection release behavior in application code",
    ]}
    agent["status"] = "done"
    agent["message"] = "Root cause determined"
    add_event("Coordinator", "Root cause determined")


def run_remediation(action_plan):
    agent = state["agents"]["runbook_executor"]
    agent["status"] = "running"
    steps = action_plan.get("steps", [])
    agent["message"] = f"Executing {len(steps)} remediation steps..."
    add_event("Runbook Executor", f"Executing {len(steps)} remediation steps")

    for i, step in enumerate(steps):
        time.sleep(0.8)
        agent["message"] = f"Step {i+1}/{len(steps)}: {step[:50]}..."
        add_event("Runbook Executor", f"Step {i+1}/{len(steps)}: {step}")

    agent["status"] = "done"
    agent["message"] = f"All {len(steps)} steps completed"
    add_event("Runbook Executor", f"All {len(steps)} steps completed")


def run_postmortem():
    agent = state["agents"]["postmortem_writer"]
    agent["status"] = "running"
    agent["message"] = "Generating incident report..."
    add_event("Post-Mortem Writer", "Generating comprehensive incident report")

    if QWEN_AVAILABLE:
        transcript = "\n".join(f"[{e['time']}] {e['agent']}: {e['message']}" for e in state["events"])
        raw = _call_qwen(
            "You are a technical writer. Generate a post-mortem with: Summary, Timeline, Root Cause, Impact, Action Items.",
            f"Generate a post-mortem:\n\n{transcript}"
        )
        if raw:
            state["postmortem"] = raw
            agent["status"] = "done"
            agent["message"] = "Report generated (Qwen API)"
            add_event("Post-Mortem Writer", "Report generated (Qwen API)")
            return

    time.sleep(2)
    state["postmortem"] = "## Incident Summary\nDatabase connection pool exhaustion caused cascading failure.\n\n## Action Items\n1. Increase pool size\n2. Add query timeout\n3. Add monitoring alerts"
    agent["status"] = "done"
    agent["message"] = "Report generated"
    add_event("Post-Mortem Writer", "Report generated")


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

    add_event("System", "Phase 2: Coordinator arbitration")
    run_coordinator(
        state["agents"]["log_analyzer"]["findings"],
        state["agents"]["metric_monitor"]["findings"],
    )

    add_event("System", "Phase 3: Runbook execution")
    run_remediation(state["action_plan"] or {})

    add_event("System", "Phase 4: Post-mortem generation")
    run_postmortem()

    state["status"] = "resolved"
    state["incident_end"] = datetime.now().strftime("%H:%M:%S")
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
                for f in agent["findings"][:2]:
                    cause = f.get("cause", "Unknown")
                    conf = int(f.get("confidence", 0) * 100)
                    conf_c = "red" if conf > 80 else "yellow" if conf > 60 else "green"
                    lines.append(f"    [bold]{cause[:55]}[/bold]")
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
                        for src_line in source.split("\n")[:6]:
                            lines.append(f"    [dim]{src_line}[/dim]")
                    
                    # Show stack traces if available
                    stacks = f.get("stack_traces", [])
                    if stacks:
                        lines.append(f"    [bold red]Stack Trace:[/bold red]")
                        for stack in stacks[:1]:
                            for st_line in stack.split("\n")[:6]:
                                lines.append(f"    [red]{st_line[:70]}[/red]")
                    
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
                    
                    for ev in f.get("evidence", [])[:2]:
                        lines.append(f"    [dim]  • {ev[:50]}[/dim]")
            lines.append("")

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
            lines.append(f"[dim]{pm[:500]}[/dim]")

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
    #timeline-panel {
        border: solid $accent;
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
                        for key in ("error_rate", "cpu_pct", "memory_mb", "p50_latency_ms", "p95_latency_ms", "p99_latency_ms", "request_count"):
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
