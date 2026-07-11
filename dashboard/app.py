"""ResQ Incident Console — SigNoz-inspired Dashboard

Run: streamlit run dashboard/app.py

Design inspired by SigNoz / Grafana incident dashboards:
- Time-series charts for all metrics
- Dark-themed metric panels
- Service health indicators
- Agent status as a pipeline view
"""

import streamlit as st
import asyncio
import json
import time
from datetime import datetime
from dotenv import load_dotenv
import pandas as pd

load_dotenv()

from integrations.qwen_client import QwenClient
from agents.log_analyzer import LogAnalyzer
from agents.metric_monitor import MetricMonitor
from agents.coordinator import Coordinator
from agents.runbook_executor import RunbookExecutor
from agents.postmortem_writer import PostMortemWriter


st.set_page_config(
    page_title="ResQ Console",
    page_icon="🚨",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---- Dark theme overrides ----
st.markdown("""
<style>
    .stMetric label { color: #94a3b8 !important; }
    .stMetric div[data-testid="stMetricValue"] { color: #f1f5f9 !important; }
    .block-container { padding-top: 1.5rem; padding-bottom: 1rem; }
    .stTabs [role="tab"] { font-size: 0.85rem; font-weight: 600; }
    .agent-pipeline {
        display: flex;
        gap: 4px;
        margin: 12px 0;
        align-items: center;
    }
    .agent-step {
        flex: 1;
        padding: 10px 8px;
        border-radius: 6px;
        text-align: center;
        font-size: 0.78rem;
        font-weight: 600;
        transition: all 0.3s;
    }
    .step-idle { background: #1e293b; color: #64748b; border: 1px solid #334155; }
    .step-working { background: #1e3a5f; color: #60a5fa; border: 1px solid #3b82f6; }
    .step-done { background: #0f3d2a; color: #34d399; border: 1px solid #10b981; }
    .step-arrow { color: #475569; font-size: 0.7rem; }
    .service-pill {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 12px;
        font-size: 0.75rem;
        font-weight: 600;
        margin: 2px 4px 2px 0;
    }
    .svc-unhealthy { background: #7f1d1d; color: #fca5a5; border: 1px solid #991b1b; }
    .svc-healthy { background: #052e16; color: #86efac; border: 1px solid #166534; }
    .activity-row {
        display: flex;
        gap: 12px;
        padding: 4px 0;
        font-size: 0.8rem;
        border-bottom: 1px solid #1e293b;
    }
    .activity-row .ts { color: #64748b; font-family: monospace; min-width: 68px; }
    .activity-row .agent { color: #93c5fd; font-weight: 600; min-width: 130px; }
    .activity-row .msg { color: #cbd5e1; }
</style>
""", unsafe_allow_html=True)

# ---- Load incident ----
with open("demo/sample_incidents/high_cpu.json") as f:
    INCIDENT = json.load(f)

# ---- State ----
for key, default in {
    "results": None,
    "activity_log": [],
    "agent_status": {
        "log_analyzer": "idle",
        "metric_monitor": "idle",
        "coordinator": "idle",
        "runbook_executor": "idle",
        "postmortem_writer": "idle",
    },
    "incident_state": "idle",
    "_start_time": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


def now_ts():
    return datetime.utcnow().strftime("%H:%M:%S")


def add_activity(agent: str, message: str):
    st.session_state.activity_log.append({"time": now_ts(), "agent": agent, "message": message})


# ============================================================
#  HEADER BAR
# ============================================================
state = st.session_state.incident_state
status_info = {
    "idle": ("No Active Incident", "⚪"),
    "triggered": ("🔴 Incident Triggered", "🔴"),
    "investigating": ("🟡 Investigating", "🟡"),
    "resolved": ("🟢 Resolved", "🟢"),
}
label, _ = status_info[state]

hdr = st.container()
with hdr:
    c1, c2, c3, c4, c5 = st.columns([3, 1, 1, 1, 1])
    c1.markdown(f"### 🚨 ResQ Incident Console  —  {label}")
    c2.metric("Severity", INCIDENT["severity"].upper())
    c3.metric("ID", INCIDENT["incident_id"])
    impact = INCIDENT.get("affected_users_estimate", "—")
    c4.metric("Impact", impact)
    elapsed = st.session_state.get("_elapsed_display", "—")
    c5.metric("Duration", str(elapsed))

# ============================================================
#  AGENT PIPELINE
# ============================================================
agent_steps = [
    ("📝 Log Analyzer", "log_analyzer"),
    ("📊 Metric Monitor", "metric_monitor"),
    ("🎯 Coordinator", "coordinator"),
    ("🔧 Runbook", "runbook_executor"),
    ("📄 Post-Mortem", "postmortem_writer"),
]

pipeline_html = '<div class="agent-pipeline">'
for i, (lbl, key) in enumerate(agent_steps):
    status = st.session_state.agent_status.get(key, "idle")
    cls = f"step-{status}"
    pipeline_html += f'<div class="agent-step {cls}">{lbl}</div>'
    if i < len(agent_steps) - 1:
        pipeline_html += '<span class="step-arrow">→</span>'
pipeline_html += "</div>"
st.markdown(pipeline_html, unsafe_allow_html=True)

# ============================================================
#  TABS
# ============================================================
tab_dashboard, tab_agents, tab_timeline, tab_postmortem = st.tabs([
    "📊  Dashboard",
    "🤖  Agents",
    "📅  Timeline",
    "📄  Post-Mortem",
])

# ============================================================
#  TAB 1 — DASHBOARD (SigNoz style: time-series + logs + services)
# ============================================================
with tab_dashboard:
    # Top row: trigger + services
    tc1, tc2 = st.columns([2, 1])
    with tc1:
        st.markdown("##### ⚠️ Trigger")
        st.info(INCIDENT["trigger"], icon="🔔")
    with tc2:
        st.markdown("##### Services")
        svc_html = ""
        for svc in INCIDENT.get("affected_services", []):
            svc_html += f'<span class="service-pill svc-unhealthy">● {svc}</span>'
        st.markdown(svc_html, unsafe_allow_html=True)

    st.divider()

    # Metrics as time-series charts
    metrics = INCIDENT.get("metrics", {})

    st.markdown("##### 📈 Metrics")
    mc1, mc2 = st.columns(2)

    # CPU
    with mc1:
        st.markdown("**CPU Utilization %**")
        cpu_df = pd.DataFrame(metrics.get("cpu_utilization", []))
        if not cpu_df.empty:
            cpu_df["timestamp"] = pd.to_datetime(cpu_df["timestamp"], format="%H:%M:%S")
            cpu_df = cpu_df.set_index("timestamp")
            st.area_chart(cpu_df[["value"]], color="#ef4444", height=160)
        st.metric("Peak", f"{max(d['value'] for d in metrics.get('cpu_utilization', [{'value':0}])):.1f}%")

    # Error Rate
    with mc2:
        st.markdown("**Error Rate %**")
        err_df = pd.DataFrame(metrics.get("error_rate_pct", []))
        if not err_df.empty:
            err_df["timestamp"] = pd.to_datetime(err_df["timestamp"], format="%H:%M:%S")
            err_df = err_df.set_index("timestamp")
            st.area_chart(err_df[["value"]], color="#f59e0b", height=160)
        st.metric("Peak", f"{max(d['value'] for d in metrics.get('error_rate_pct', [{'value':0}])):.1f}%")

    mc3, mc4 = st.columns(2)

    # Memory
    with mc3:
        st.markdown("**Memory Usage (GB)**")
        mem_df = pd.DataFrame(metrics.get("memory_usage_gb", []))
        if not mem_df.empty:
            mem_df["timestamp"] = pd.to_datetime(mem_df["timestamp"], format="%H:%M:%S")
            mem_df = mem_df.set_index("timestamp")
            st.area_chart(mem_df[["value"]], color="#8b5cf6", height=160)
        st.metric("Peak", f"{max(d['value'] for d in metrics.get('memory_usage_gb', [{'value':0}])):.1f} GB")

    # Latency
    with mc4:
        st.markdown("**P99 Latency (ms)**")
        lat_df = pd.DataFrame(metrics.get("request_latency_p99_ms", []))
        if not lat_df.empty:
            lat_df["timestamp"] = pd.to_datetime(lat_df["timestamp"], format="%H:%M:%S")
            lat_df = lat_df.set_index("timestamp")
            st.area_chart(lat_df[["value"]], color="#f97316", height=160)
        st.metric("Peak", f"{max(d['value'] for d in metrics.get('request_latency_p99_ms', [{'value':0}])):.0f} ms")

    # DB Connection Pool
    st.markdown("**DB Connection Pool**")
    db_df = pd.DataFrame(metrics.get("db_connection_pool", []))
    if not db_df.empty:
        db_df["timestamp"] = pd.to_datetime(db_df["timestamp"], format="%H:%M:%S")
        db_df = db_df.set_index("timestamp")
        st.area_chart(db_df[["value"]], color="#3b82f6", height=140)
    st.metric("Max Pool", f"{max(d['value'] for d in metrics.get('db_connection_pool', [{'value':0}])):.0f} / 500")

    st.divider()

    # Logs panel
    st.markdown("##### 📋 Log Stream")
    st.code(INCIDENT.get("logs", "")[:1200], language="log")

# ============================================================
#  TAB 2 — AGENTS
# ============================================================
with tab_agents:
    for icon, name, key in [
        ("📝", "Log Analyzer", "log_analyzer"),
        ("📊", "Metric Monitor", "metric_monitor"),
        ("🎯", "Coordinator", "coordinator"),
        ("🔧", "Runbook Executor", "runbook_executor"),
        ("📄", "Post-Mortem Writer", "postmortem_writer"),
    ]:
        status = st.session_state.agent_status.get(key, "idle")
        result = (st.session_state.results or {}).get(key)

        with st.expander(f"{icon} **{name}**  —  {status.upper()}", expanded=(status == "working")):
            if status == "idle":
                st.caption("Waiting…")
            elif status == "working":
                st.caption("Processing…")
            elif result:
                hyps = result.get("hypotheses", [])
                if hyps:
                    # Table of hypotheses
                    rows = []
                    for i, h in enumerate(hyps):
                        rows.append({
                            "#": i + 1,
                            "Confidence": f"{int(h.get('confidence', 0) * 100)}%",
                            "Severity": h.get("severity", ""),
                            "Cause": h.get("cause", ""),
                            "Evidence": " • ".join(h.get("evidence", [])[:2]),
                        })
                    st.dataframe(
                        pd.DataFrame(rows),
                        column_config={
                            "#": st.column_config.NumberColumn(format="%d"),
                            "Confidence": st.column_config.TextColumn(),
                            "Severity": st.column_config.TextColumn(),
                            "Cause": st.column_config.TextColumn(width="medium"),
                            "Evidence": st.column_config.TextColumn(width="large"),
                        },
                        hide_index=True,
                        use_container_width=True,
                    )
                elif key == "coordinator":
                    rc = result.get("root_cause", {})
                    if rc:
                        st.success(f"**Root Cause:** {rc.get('cause')}")
                        c1, c2 = st.columns(2)
                        c1.metric("Confidence", f"{int(rc.get('confidence', 0) * 100)}%")
                        c2.metric("Severity", rc.get("severity", "").upper())
                        st.caption(result.get("justification", ""))
                    ap = result.get("action_plan", {})
                    if ap.get("steps"):
                        with st.expander("Action Plan"):
                            st.text(ap["steps"][:1500])
                elif key == "runbook_executor":
                    if result.get("status") == "completed":
                        st.success("✅ Remediation completed")
                        detail = result.get("steps_executed", {}).get("execution_detail", "")
                        if isinstance(detail, str) and detail:
                            with st.expander("Execution Detail"):
                                st.text(detail[:2000])
                elif key == "postmortem_writer":
                    if result.get("postmortem"):
                        st.success("✅ Post-mortem report generated")

# ============================================================
#  TAB 3 — TIMELINE
# ============================================================
with tab_timeline:
    if not st.session_state.activity_log:
        st.info("No events yet. Trigger an incident.")
    else:
        # Render as a table
        tl_rows = []
        for ev in st.session_state.activity_log:
            tl_rows.append({"Time": ev["time"], "Agent": ev["agent"], "Event": ev["message"]})
        st.dataframe(
            pd.DataFrame(tl_rows),
            column_config={
                "Time": st.column_config.TextColumn(width="small"),
                "Agent": st.column_config.TextColumn(width="medium"),
                "Event": st.column_config.TextColumn(width="large"),
            },
            hide_index=True,
            use_container_width=True,
        )

# ============================================================
#  TAB 4 — POST-MORTEM
# ============================================================
with tab_postmortem:
    pm_text = (st.session_state.results or {}).get("postmortem", {}).get("postmortem", "")
    if pm_text:
        st.markdown(pm_text)
    else:
        st.info("Post-mortem will appear after incident resolution.")

# ============================================================
#  CONTROLS
# ============================================================
st.divider()
col_btn, col_info = st.columns([1, 3])
with col_btn:
    if st.button("▶️ Trigger Incident", type="primary", use_container_width=True, disabled=state != "idle"):
        pass  # handled below
    if state != "idle" and st.button("🔄 New Incident", use_container_width=True):
        st.session_state.incident_state = "idle"
        st.session_state.results = None
        st.session_state.activity_log = []
        st.session_state.agent_status = {k: "idle" for k in st.session_state.agent_status}
        st.session_state._elapsed_display = "—"
        st.rerun()

with col_info:
    if state != "idle":
        st.caption("Incident is active — agents are working.")

st.divider()
st.caption("ResQ — Multi-Agent Incident Response · Qwen Cloud Global AI Hackathon")

# ============================================================
#  RUNNER
# ============================================================
async def run_incident():
    qwen = QwenClient()
    with open("demo/sample_incidents/high_cpu.json") as f:
        data = json.load(f)

    la = LogAnalyzer(qwen)
    mm = MetricMonitor(qwen)
    co = Coordinator(qwen)
    re = RunbookExecutor(qwen)
    pw = PostMortemWriter(qwen)

    results = {}

    # Phase 1
    st.session_state.incident_state = "investigating"
    st.session_state.agent_status["log_analyzer"] = "working"
    st.session_state.agent_status["metric_monitor"] = "working"
    add_activity("System", "Incident triggered — parallel diagnosis started")
    st.rerun()

    lr, mr = await asyncio.gather(la.analyze(data), mm.analyze(data))
    results["log_analyzer"] = lr
    results["metric_monitor"] = mr
    st.session_state.agent_status["log_analyzer"] = "done"
    st.session_state.agent_status["metric_monitor"] = "done"
    add_activity("Log Analyzer", f"{len(lr['hypotheses'])} hypotheses produced")
    add_activity("Metric Monitor", f"{len(mr['hypotheses'])} hypotheses produced")
    st.rerun()

    # Phase 2
    st.session_state.agent_status["coordinator"] = "working"
    add_activity("Coordinator", "Arbitration started")
    st.rerun()

    arb = await co.arbitrate(lr.get("hypotheses", []), mr.get("hypotheses", []))
    results["coordinator"] = arb
    st.session_state.agent_status["coordinator"] = "done"
    rc = arb.get("root_cause", {})
    add_activity("Coordinator", f"Root cause: {rc.get('cause','')[:60]}…")
    st.rerun()

    # Phase 3
    st.session_state.agent_status["runbook_executor"] = "working"
    add_activity("Runbook Executor", "Executing remediation")
    st.rerun()

    ex = await re.execute(arb.get("action_plan", {}))
    results["runbook_executor"] = ex
    st.session_state.agent_status["runbook_executor"] = "done"
    add_activity("Runbook Executor", f"Remediation {ex.get('status','unknown')}")
    st.rerun()

    # Phase 4
    st.session_state.agent_status["postmortem_writer"] = "working"
    add_activity("Post-Mortem Writer", "Generating report")
    st.rerun()

    pm = await pw.generate_postmortem(results)
    results["postmortem"] = pm
    st.session_state.agent_status["postmortem_writer"] = "done"
    add_activity("Post-Mortem Writer", "Report generated")
    add_activity("System", "Incident resolved")

    elapsed = time.time() - st.session_state.get("_start_time", time.time())
    results["metadata"] = {
        "total_time_seconds": round(elapsed, 2),
        "agents_used": 5,
        "log_source": lr.get("log_source", "static"),
    }

    st.session_state.results = results
    st.session_state.incident_state = "resolved"
    st.session_state._elapsed_display = f"{elapsed:.0f}s"
    st.rerun()


if state in ("triggered", "investigating") and not st.session_state.results:
    st.session_state._start_time = time.time()
    asyncio.run(run_incident())
