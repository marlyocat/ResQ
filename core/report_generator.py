"""Incident Report Generator — produces a self-contained HTML report with charts.

Usage:
    from core.report_generator import ReportGenerator
    rg = ReportGenerator()
    rg.generate(incident_data, results, output_path="demo/incident_report.html")
"""

import json
from datetime import datetime
from typing import Optional


class ReportGenerator:
    """Generates a professional HTML incident report."""

    def generate(self, incident_data: dict, results: dict, output_path: str):
        """Generate a complete HTML incident report with charts, timeline, and findings."""
        html = self._build_report(incident_data, results)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        return output_path

    def _build_report(self, incident: dict, results: dict) -> str:
        """Build the full HTML report."""
        log_data = results.get("log_analyzer", {})
        metric_data = results.get("metric_monitor", {})
        coord_data = results.get("coordinator", {})
        exec_data = results.get("runbook_executor", {})
        pm_data = results.get("postmortem", {})
        metadata = results.get("metadata", {})

        # Build chart data JSON
        metrics = incident.get("metrics", {})
        chart_data = {
            "cpu": self._extract_chart_data(metrics.get("cpu_utilization", [])),
            "error_rate": self._extract_chart_data(metrics.get("error_rate_pct", [])),
            "memory": self._extract_chart_data(metrics.get("memory_usage_gb", [])),
            "latency": self._extract_chart_data(metrics.get("request_latency_p99_ms", [])),
            "db_pool": self._extract_chart_data(metrics.get("db_connection_pool", [])),
        }

        # Build timeline events
        timeline_events = [
            {"time": incident.get("timestamp", ""), "agent": "System", "event": incident.get("trigger", "")},
        ]
        # Add agent completion events from results
        if log_data.get("hypotheses"):
            timeline_events.append({"time": "", "agent": "Log Analyzer", "event": f"Produced {len(log_data['hypotheses'])} hypotheses"})
        if metric_data.get("hypotheses"):
            timeline_events.append({"time": "", "agent": "Metric Monitor", "event": f"Produced {len(metric_data['hypotheses'])} hypotheses"})
        rc = coord_data.get("root_cause", {})
        if rc.get("cause"):
            timeline_events.append({"time": "", "agent": "Coordinator", "event": f"Root cause: {rc['cause'][:60]}..."})
        if exec_data.get("status") == "completed":
            timeline_events.append({"time": "", "agent": "Runbook Executor", "event": "Remediation completed"})
        if pm_data.get("postmortem"):
            timeline_events.append({"time": "", "agent": "Post-Mortem Writer", "event": "Report generated"})

        # Pre-compute peak values
        peak_cpu = max((d["value"] for d in metrics.get("cpu_utilization", [{"value": 0}])), default=0)
        peak_err = max((d["value"] for d in metrics.get("error_rate_pct", [{"value": 0}])), default=0)
        peak_mem = max((d["value"] for d in metrics.get("memory_usage_gb", [{"value": 0}])), default=0)
        peak_lat = max((d["value"] for d in metrics.get("request_latency_p99_ms", [{"value": 0}])), default=0)
        peak_db = max((d["value"] for d in metrics.get("db_connection_pool", [{"value": 0}])), default=0)

        affected_svcs = "".join(f'<span class="svc-pill">{s}</span>' for s in incident.get("affected_services", []))
        timeline_html = "".join(
            f'<div class="timeline-item"><div class="time">{e["time"]}</div><div class="agent">{e["agent"]}</div><div class="event">{e["event"]}</div></div>'
            for e in timeline_events
        )
        log_hyps_html = self._render_hypotheses(log_data.get("hypotheses", []))
        met_hyps_html = self._render_hypotheses(metric_data.get("hypotheses", []))

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ResQ Incident Report — {incident.get('incident_id', 'INCIDENT')}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f172a;
            color: #e2e8f0;
            line-height: 1.6;
            padding: 2rem;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        .header {{
            background: linear-gradient(135deg, #1e293b, #0f172a);
            border: 1px solid #334155;
            border-radius: 12px;
            padding: 1.5rem 2rem;
            margin-bottom: 1.5rem;
        }}
        .header h1 {{ font-size: 1.5rem; color: #f8fafc; }}
        .header .meta {{ display: flex; gap: 1.5rem; margin-top: 0.5rem; font-size: 0.85rem; color: #94a3b8; }}
        .badge {{
            display: inline-block;
            padding: 2px 10px;
            border-radius: 12px;
            font-size: 0.75rem;
            font-weight: 600;
        }}
        .badge-critical {{ background: #7f1d1d; color: #fca5a5; }}
        .badge-high {{ background: #7c2d12; color: #fdba74; }}
        .badge-resolved {{ background: #052e16; color: #86efac; }}
        .section {{
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 12px;
            padding: 1.25rem;
            margin-bottom: 1rem;
        }}
        .section h2 {{
            font-size: 1rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: #94a3b8;
            margin-bottom: 0.75rem;
            padding-bottom: 0.5rem;
            border-bottom: 1px solid #334155;
        }}
        .metric-row {{ display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 1rem; }}
        .metric-card {{
            flex: 1;
            min-width: 180px;
            background: #0f172a;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 1rem;
        }}
        .metric-card .label {{ font-size: 0.75rem; color: #64748b; text-transform: uppercase; }}
        .metric-card .value {{ font-size: 1.5rem; font-weight: 700; color: #f1f5f9; margin-top: 0.25rem; }}
        .chart-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(350px, 1fr)); gap: 1rem; margin-bottom: 1rem; }}
        .chart-box {{ background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 1rem; }}
        .chart-box canvas {{ max-height: 180px; }}
        .timeline {{ border-left: 2px solid #334155; padding-left: 1.5rem; }}
        .timeline-item {{ position: relative; padding: 0.75rem 0; }}
        .timeline-item::before {{
            content: "";
            position: absolute;
            left: -1.65rem;
            top: 1rem;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: #3b82f6;
            border: 2px solid #0f172a;
        }}
        .timeline-item .time {{ font-size: 0.8rem; color: #64748b; font-family: monospace; }}
        .timeline-item .agent {{ font-weight: 600; color: #93c5fd; }}
        .timeline-item .event {{ color: #cbd5e1; }}
        .agent-cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1rem; }}
        .agent-card {{ background: #0f172a; border: 1px solid #334155; border-radius: 8px; overflow: hidden; }}
        .agent-card-header {{ padding: 0.75rem 1rem; background: #1e293b; border-bottom: 1px solid #334155; font-weight: 600; }}
        .agent-card-body {{ padding: 1rem; }}
        .hypothesis {{ padding: 0.5rem 0; border-bottom: 1px solid #1e293b; }}
        .hypothesis:last-child {{ border-bottom: none; }}
        .hyp-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.25rem; }}
        .hyp-confidence {{ font-family: monospace; font-weight: 600; }}
        .hyp-bar {{ height: 4px; background: #334155; border-radius: 2px; overflow: hidden; margin-top: 4px; }}
        .hyp-fill {{ height: 100%; border-radius: 2px; }}
        .root-cause {{
            background: linear-gradient(135deg, #052e16, #0f3d2a);
            border: 1px solid #166534;
            border-radius: 8px;
            padding: 1rem;
            margin-bottom: 1rem;
        }}
        .root-cause h3 {{ color: #34d399; font-size: 0.9rem; margin-bottom: 0.5rem; }}
        .services {{ display: flex; gap: 0.5rem; flex-wrap: wrap; margin-top: 0.5rem; }}
        .svc-pill {{ padding: 2px 10px; border-radius: 12px; font-size: 0.75rem; background: #7f1d1d; color: #fca5a5; }}
        .postmortem {{ white-space: pre-wrap; font-size: 0.85rem; line-height: 1.7; color: #cbd5e1; max-height: 400px; overflow-y: auto; }}
        .footer {{ text-align: center; color: #475569; font-size: 0.75rem; margin-top: 2rem; padding-top: 1rem; border-top: 1px solid #1e293b; }}
    </style>
</head>
<body>
<div class="container">
    <!-- Header -->
    <div class="header">
        <h1>🚨 Incident Report: {incident.get('incident_id', 'INCIDENT')}</h1>
        <div class="meta">
            <span>Severity: <span class="badge badge-{incident.get('severity', 'high')}">{incident.get('severity', 'high').upper()}</span></span>
            <span>Status: <span class="badge badge-resolved">RESOLVED</span></span>
            <span>Duration: {metadata.get('total_time_seconds', 0):.0f}s</span>
            <span>Impact: {incident.get('affected_users_estimate', '—')}</span>
        </div>
        <div class="services">
            {affected_svcs}
        </div>
    </div>

    <!-- Key Metrics -->
    <div class="section">
        <h2>Key Metrics</h2>
        <div class="metric-row">
            <div class="metric-card">
                <div class="label">Peak CPU</div>
                <div class="value">{peak_cpu:.1f}%</div>
            </div>
            <div class="metric-card">
                <div class="label">Peak Error Rate</div>
                <div class="value">{peak_err:.1f}%</div>
            </div>
            <div class="metric-card">
                <div class="label">Peak Memory</div>
                <div class="value">{peak_mem:.1f} GB</div>
            </div>
            <div class="metric-card">
                <div class="label">Peak P99 Latency</div>
                <div class="value">{peak_lat:.0f} ms</div>
            </div>
            <div class="metric-card">
                <div class="label">Max DB Connections</div>
                <div class="value">{peak_db:.0f} / 500</div>
            </div>
        </div>
    </div>

    <!-- Charts -->
    <div class="section">
        <h2>Metric Trends</h2>
        <div class="chart-grid">
            <div class="chart-box"><canvas id="chart-cpu"></canvas></div>
            <div class="chart-box"><canvas id="chart-err"></canvas></div>
            <div class="chart-box"><canvas id="chart-mem"></canvas></div>
            <div class="chart-box"><canvas id="chart-lat"></canvas></div>
            <div class="chart-box" style="grid-column: span 2;"><canvas id="chart-db"></canvas></div>
        </div>
    </div>

    <!-- Root Cause -->
    <div class="root-cause">
        <h3>✅ Root Cause Determined</h3>
        <p style="font-size:1rem;font-weight:600;">{rc.get('cause', 'Unknown')}</p>
        <p style="font-size:0.85rem;color:#86efac;margin-top:0.25rem;">Confidence: {int(rc.get('confidence', 0) * 100)}% | Severity: {rc.get('severity', 'unknown').upper()}</p>
        <p style="font-size:0.8rem;color:#a7f3d0;margin-top:0.5rem;">{coord_data.get('justification', '')[:300]}</p>
    </div>

    <!-- Agent Findings -->
    <div class="section">
        <h2>Agent Findings</h2>
        <div class="agent-cards">
            <div class="agent-card">
                <div class="agent-card-header">📝 Log Analyzer — {len(log_data.get('hypotheses', []))} hypotheses</div>
                <div class="agent-card-body">
                    {log_hyps_html}
                </div>
            </div>
            <div class="agent-card">
                <div class="agent-card-header">📊 Metric Monitor — {len(metric_data.get('hypotheses', []))} hypotheses</div>
                <div class="agent-card-body">
                    {met_hyps_html}
                </div>
            </div>
        </div>
    </div>

    <!-- Timeline -->
    <div class="section">
        <h2>Incident Timeline</h2>
        <div class="timeline">
            {timeline_html}
        </div>
    </div>

    <!-- Post-Mortem -->
    <div class="section">
        <h2>Post-Mortem Summary</h2>
        <div class="postmortem">{pm_data.get('postmortem', 'No post-mortem generated.')[:2000]}</div>
    </div>

    <div class="footer">
        Generated by ResQ — Multi-Agent Incident Response · {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}
    </div>
</div>

<script>
const chartData = {json.dumps(chart_data)};

const chartOpts = (labelKey, color) => ({{
    type: 'line',
    data: {{
        labels: chartData[labelKey].map(d => d.time),
        datasets: [{{
            label: labelKey,
            data: chartData[labelKey].map(d => d.value),
            borderColor: color,
            backgroundColor: color + '33',
            fill: true,
            tension: 0.4,
            pointRadius: 3,
            pointHoverRadius: 5,
        }}]
    }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{ legend: {{ display: false }} }},
        scales: {{
            x: {{ grid: {{ color: '#1e293b' }}, ticks: {{ color: '#64748b', maxTicksLimit: 5 }} }},
            y: {{ grid: {{ color: '#1e293b' }}, ticks: {{ color: '#64748b' }} }}
        }}
    }}
}});

new Chart(document.getElementById('chart-cpu'), chartOpts('cpu', '#ef4444'));
new Chart(document.getElementById('chart-err'), chartOpts('error_rate', '#f59e0b'));
new Chart(document.getElementById('chart-mem'), chartOpts('memory', '#8b5cf6'));
new Chart(document.getElementById('chart-lat'), chartOpts('latency', '#f97316'));
new Chart(document.getElementById('chart-db'), chartOpts('db_pool', '#3b82f6'));
</script>
</body>
</html>"""
        return html

    def _extract_chart_data(self, data_points: list) -> list:
        """Extract time-value pairs for Chart.js."""
        return [{"time": dp["timestamp"], "value": dp["value"]} for dp in data_points]

    def _render_hypotheses(self, hypotheses: list) -> str:
        """Render hypothesis cards as HTML."""
        if not hypotheses:
            return '<p style="color:#64748b;font-size:0.85rem">No hypotheses produced</p>'
        html = ""
        for i, h in enumerate(hypotheses[:3]):
            conf = h.get("confidence", 0)
            pct = int(conf * 100)
            sev = h.get("severity", "medium")
            cause = h.get("cause", "")
            color = {"critical": "#ef4444", "high": "#f97316", "medium": "#eab308", "low": "#22c55e"}.get(sev, "#64748b")
            html += f"""
            <div class="hypothesis">
                <div class="hyp-header">
                    <span style="font-size:0.85rem;font-weight:600">{cause[:70]}...</span>
                    <span class="hyp-confidence" style="color:{color}">{pct}%</span>
                </div>
                <div class="hyp-bar"><div class="hyp-fill" style="width:{pct}%;background:{color}"></div></div>
            </div>"""
        return html
