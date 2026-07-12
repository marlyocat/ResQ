# ResQ Architecture

## System Overview

ResQ is a multi-agent incident response system that connects to real production infrastructure (logs, metrics, source code, databases) and automatically investigates incidents. Five specialized agents collaborate through a coordinator to diagnose root causes, execute remediation, and generate comprehensive post-mortem reports.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         INCIDENT DETECTION                              │
│         (Alert Webhook / Metric Polling / Log Analysis)                 │
└────────────────────────────────────────────────────────────────────────┘
                                 │
          ┌──────────────────────┴──────────────────────┐
          ▼                                             ▼
┌───────────────────────┐                   ┌───────────────────────────┐
│    Log Analyzer       │                   │     Metric Monitor        │
│  (SLS/Local logs)     │                   │  (Prometheus metrics)     │
└───────────┬───────────┘                   └─────────────┬─────────────┘
            │  diagnosis hypotheses                       │  diagnosis hypotheses
            └──────────────┬──────────────────────────────┘
                           ▼
              ┌────────────────────────
              │     Coordinator        │
              │ (conflict resolution,  │
              │  root cause arbitration)│
              └────────────┬───────────┘
                           │ verified root cause + action plan
                           ▼
              ┌────────────────────────┐
              │   Runbook Executor     │
              │ (automated remediation)│
              └───────────────────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │  Post-Mortem Writer    │
              │ (incident documentation)│
              ────────────┬───────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │   OSS Report Storage   │
              │  (Alibaba Cloud OSS)   │
              └────────────────────────

All agents powered by Qwen Cloud APIs
Integrations: SLS, Prometheus, GitHub, Redis, PostgreSQL, Kafka, OSS
```

## Agent Roles

### 1. Log Analyzer Agent
**Responsibility:** Parse and analyze application/system logs to identify error patterns, anomalies, and potential root causes.

**Input:** Logs from SLS or local files
**Output:** Diagnostic hypotheses with confidence scores, code locations, stack traces

**Capabilities:**
- Pattern matching for known error signatures
- Temporal correlation of log events
- Error rate analysis
- Stack trace extraction and analysis
- Source code lookup at error locations

**Integration:** Alibaba Cloud SLS, local log files

---

### 2. Metric Monitor Agent
**Responsibility:** Analyze system metrics (CPU, memory, latency, throughput, error rates) to detect anomalies and correlate with incident signals.

**Input:** Time-series metrics from Prometheus
**Output:** Diagnostic hypotheses with confidence scores

**Capabilities:**
- Anomaly detection on metric streams
- Cross-metric correlation (e.g., CPU spike + latency increase)
- Baseline comparison
- Capacity analysis

**Integration:** Prometheus API

---

### 3. Runbook Executor Agent
**Responsibility:** Execute verified remediation actions based on the Coordinator's arbitration decision.

**Input:** Approved action plan from Coordinator
**Output:** Execution results and status

**Capabilities:**
- Runbook selection and adaptation
- Safe execution with rollback capability
- Action verification (did the fix work?)
- Escalation triggers

---

### 4. Post-Mortem Writer Agent
**Responsibility:** Generate comprehensive incident documentation including timeline, root cause, impact, and action items.

**Input:** Full incident transcript from all agents, actual metrics, findings
**Output:** Structured post-mortem document grounded in real data

**Capabilities:**
- Timeline reconstruction with actual timestamps
- Root cause synthesis from agent findings
- Impact assessment using real metric values
- Actionable follow-up items

---

### 5. Coordinator Agent
**Responsibility:** Arbitrate between competing hypotheses from Log Analyzer and Metric Monitor, resolve conflicts, and produce a verified action plan.

**Input:** Diagnostic hypotheses from Log Analyzer + Metric Monitor
**Output:** Verified root cause + action plan for Runbook Executor

**Capabilities:**
- Hypothesis comparison and weighting
- Conflict detection and resolution
- Confidence aggregation
- Decision justification

---

## Integration Layer

### Log Sources
- **Alibaba Cloud SLS** — Production log ingestion and querying
- **Local files** — Development/testing logs

### Metrics Sources
- **Prometheus** — Time-series metrics collection
- **Custom endpoints** — Application-specific metrics

### Source Code
- **Local repository** — Direct file system access
- **GitHub** — API-based repository access

### Infrastructure Probes
- **Redis** — Cache health, memory usage, connection count
- **PostgreSQL** — Database health, active connections, version
- **Kafka** — Topic count, consumer groups
- **RabbitMQ** — Queue health checks

### Alert Ingestion
- **Webhook server** — Receives alerts from Grafana, PagerDuty, etc.
- **Normalized format** — Converts various alert formats to standard schema

### Report Storage
- **Alibaba Cloud OSS** — Incident reports stored as JSON
- **Structured paths** — `incidents/YYYY-MM-DD/incident_id.json`

---

## Communication Protocol

### Message Format

All inter-agent communication uses a structured JSON format:

```json
{
  "message_id": "uuid",
  "sender": "log_analyzer",
  "recipient": "coordinator",
  "timestamp": "ISO-8601",
  "type": "diagnosis_hypothesis",
  "payload": {
    "hypotheses": [
      {
        "cause": "Memory leak in service-x",
        "confidence": 0.85,
        "evidence": ["RSS growth 2GB in 30min", "OOM kill at 14:32"],
        "severity": "high",
        "code_location": {
          "file": "src/service.py",
          "function": "handle_request",
          "line": 142
        }
      }
    ],
    "incident_id": "INC-2024-001"
  }
}
```

### Message Types

| Type | Sender | Recipient | Description |
|------|--------|-----------|-------------|
| `diagnosis_hypothesis` | Log Analyzer / Metric Monitor | Coordinator | Independent analysis results |
| `arbitration_request` | Coordinator | — | Trigger for conflict resolution |
| `action_plan` | Coordinator | Runbook Executor | Approved remediation steps |
| `execution_result` | Runbook Executor | Coordinator | Remediation outcome |
| `incident_complete` | Coordinator | Post-Mortem Writer | Signal to generate documentation |
| `postmortem` | Post-Mortem Writer | — | Final incident report |

---

## Conflict Resolution Mechanism

The Coordinator uses a **weighted evidence scoring** algorithm:

1. **Collect hypotheses** from Log Analyzer and Metric Monitor
2. **Cross-reference** evidence — do both agents point to the same cause?
3. **Score each hypothesis:**
   - Base confidence from agent (0-1)
   - Evidence strength bonus (more evidence = higher weight)
   - Cross-agent confirmation bonus (+0.15 if both agents agree)
4. **Select top hypothesis** or request re-analysis if no clear winner
5. **Justify decision** with evidence summary

### Example Conflict Scenario

```
Log Analyzer: "Database connection pool exhausted (confidence: 0.80)"
  Evidence: [connection timeout errors, pool size at max]
  Code: src/db.py:142 (get_connection)

Metric Monitor: "CPU throttling due to runaway query (confidence: 0.75)"
  Evidence: [CPU spike at 95%, query latency 10x baseline]

Coordinator Resolution:
  → Both point to database issues, different root causes
  → Cross-check: connection exhaustion can cause CPU spike (waiting queries pile up)
  → Final: "Database connection pool exhaustion causing cascade (confidence: 0.85)"
  → Action: Increase pool size + add query timeout
```

---

## Incident Detection Methods

### 1. Alert Webhook (Recommended)
```
Grafana/PagerDuty → POST /webhook/alert → ResQ investigates
```

### 2. Metric Polling
```python
# Every 30 seconds
error_rate = prometheus.get_error_rate("my-app")
if error_rate > 0.05:  # 5% threshold
    trigger_investigation()
```

### 3. Log Analysis
```python
# Every minute
recent_errors = sls.query("level: ERROR | SELECT count(*) as cnt")
if recent_errors > baseline * 3:  # 3x normal
    trigger_investigation()
```

---

## Data Flow

```
1. Incident trigger (webhook alert / metric anomaly / log spike)
   ↓
2. Log Analyzer + Metric Monitor (parallel execution)
   ↓  (each queries real infrastructure)
3. Source Code Indexer (reads code at error locations)
   ↓
4. Infrastructure Probes (check Redis/DB/Kafka health)
   ↓
5. Coordinator receives all analyses
   ↓  (conflict resolution)
6. Coordinator produces action plan
   ↓
7. Runbook Executor applies fix
   ↓  (verifies result)
8. Post-Mortem Writer generates report (grounded in actual data)
   ↓
9. Report uploaded to OSS
   ↓
10. Incident closed
```

---

## Terminal UI

ResQ includes a real-time terminal UI built with Textual:

```
┌─ Service Metrics ────────────────────────────────────────────────────────┐
│ Error Rate:  19.2%                                                       │
│ CPU:         0.0%                                                        │
│ Memory:      46 MB                                                       │
│ P99 Latency: 4797 ms                                                     │
└──────────────────────────────────────────────────────────────────────────┘

─ Agent Investigation ────────────────────────────────────────────────────┐
│ ✓ 📝 Log Analyzer  Produced 2 hypotheses (Qwen API)                      │
│     The `get_users` function at line 205 in `target/app.py`              │
│     Confidence: 95%                                                      │
│     Code: target/app.py:205 (get_users)                                  │
│     Source:                                                              │
│           200:             _record(latency)                              │
│           201:             logger.info(...)                              │
│           202:             return jsonify(...)                           │
│           203:                                                           │
│           204:         conn = sqlite3.connect(...)                       │
│           205:         conn.row_factory = sqlite3.Row                    │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Technology Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **LLM** | Qwen Cloud (qwen-plus) | Agent reasoning and analysis |
| **Terminal UI** | Textual + Rich | Live investigation display |
| **Logs** | Alibaba Cloud SLS | Log ingestion and querying |
| **Metrics** | Prometheus | Time-series metrics |
| **Storage** | Alibaba Cloud OSS | Report storage |
| **Source Code** | Local/GitHub | Code analysis |
| **Infrastructure** | Redis, PostgreSQL, Kafka | Health probes |
| **Deployment** | Docker + Terraform | Infrastructure as code |

---

## Multi-Agent vs Single-Agent Comparison

### Why Multi-Agent Wins

| Aspect | Single Agent | Multi-Agent (ResQ) |
|--------|-------------|-------------------|
| **Context window** | Must hold all signals in one prompt | Each agent focuses on one signal type |
| **Diagnostic depth** | Broad but shallow analysis | Deep, specialized analysis per agent |
| **Conflict detection** | No internal debate | Agents independently diagnose, conflicts surfaced |
| **Hallucination risk** | Higher — fabricates connections | Lower — evidence must be grounded in data |
| **Scalability** | Linear — one prompt chain | Parallel — agents can run concurrently |
| **Auditability** | Single narrative, hard to trace | Each agent's reasoning is transparent |

---

## Alibaba Cloud Integration

ResQ demonstrates comprehensive Alibaba Cloud API usage:

1. **SLS (Simple Log Service)** — Log ingestion and querying via API
2. **OSS (Object Storage Service)** — Incident report storage
3. **ECS (Elastic Compute Service)** — Hosting the agent orchestration service
4. **Terraform** — Infrastructure provisioning via `deploy/terraform/`

See `integrations/` directory for all integration implementations.

---

## Configuration

All integrations configured via `.env` file:

```bash
# Required
QWEN_API_KEY=your_key

# Logs
SLS_PROJECT=your-project
SLS_LOGSTORE=your-logstore

# Metrics
PROMETHEUS_URL=http://localhost:9090

# Source Code
SOURCE_LOCAL_PATH=/path/to/repo

# Infrastructure
REDIS_URL=redis://localhost:6379
DATABASE_URL=postgresql://user:pass@host:5432/db

# Report Storage
OSS_ENDPOINT=https://oss-cn-hangzhou.aliyuncs.com
OSS_BUCKET_NAME=resq-reports

# Alerts
RESQ_WEBHOOK_PORT=5001
```

See `.env.example` for complete configuration template.
