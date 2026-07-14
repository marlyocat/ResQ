# ResQ Architecture

## System Overview

ResQ is a multi-agent incident response system that connects to real production infrastructure (logs, metrics, source code, databases) and automatically investigates incidents. Five specialized agents collaborate — dividing the work, **negotiating when they disagree**, and arbitrating a final answer — to diagnose root causes, execute remediation, and generate comprehensive post-mortem reports.

## Architecture Diagram

See [`docs/architecture.svg`](docs/architecture.svg) for the full diagram. The workflow runs in four phases:

```
INCIDENT DETECTION  (metric threshold crossed / incident fixture / SLS window)
        │
        ▼
PHASE 1 · Parallel diagnosis        Log Analyzer  ‖  Metric Monitor
        │                           (each from its own data source)
        ▼
PHASE 1.5 · Negotiation             on disagreement, agents exchange
        │                           hypotheses + evidence (via MessageBus)
        │                           and revise — cause vs. symptom, timeline
        ▼
PHASE 2 · Arbitration               Coordinator + ConsensusEngine
        │                           → final root cause
        ▼
PHASE 3 · Remediation               Runbook Executor
        ▼
PHASE 4 · Documentation             Post-Mortem Writer → OSS report storage
```

All agents are powered by Qwen Cloud (qwen-plus). The target service runs on Alibaba Cloud ECS and exercises SLS, OSS, ECS, and CMS.

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

**Input:** Time-series metrics from the target service's `/api/metrics` (or the incident fixture)
**Output:** Diagnostic hypotheses with confidence scores

**Capabilities:**
- Anomaly detection on metric streams
- Cross-metric correlation (e.g., CPU spike + latency increase)
- Baseline comparison
- Capacity analysis

**Integration:** target service `/api/metrics` (the deployed service exposes host metrics via Alibaba CMS)

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

### Negotiation Round (Phase 1.5)

Between parallel diagnosis and arbitration, ResQ runs a **negotiation round** — the "dialogue and negotiation" step. It is not a separate agent; it is a structured exchange between the Log Analyzer and Metric Monitor, implemented in [`core/negotiation.py`](core/negotiation.py).

**Trigger:** the two specialists' top hypotheses name *different* root causes (heuristic overlap check).

**Mechanism:** each agent is shown the other's hypotheses and evidence and asked to re-examine the incident — distinguishing a root cause from a downstream *symptom*, and using the timeline of which signal moved first — then to revise or defend its position. The exchange is routed over the `MessageBus` and recorded for audit.

**Why it matters:** it lets a well-supported minority hypothesis override a loud-but-wrong one. On an ambiguous incident whose logs point at a memory leak but whose metrics reveal a cache failure, naive arbitration follows the loud signal and misdiagnoses; the negotiation round flips it to the correct root cause (see [Conflict Resolution](#conflict-resolution-mechanism) and [`docs/baseline_comparison.md`](docs/baseline_comparison.md)).

---

## Integration Layer

### Log Sources
- **Alibaba Cloud SLS** — Production log ingestion and querying (`--sls-incident`)
- **Target service `/api/logs`** — the live TUI reads the target's log buffer
- **Incident fixtures** — captured logs in `demo/sample_incidents/*.json`

### Metrics Sources
- **Target service `/api/metrics`** — request rate, error rate, latency percentiles, CPU/memory
- **Incident fixtures** — captured metric series for the batch pipeline / baseline comparison

### Source Code
- **Local repository** — the Log Analyzer reads code at error locations (from `[file:…, func:…]` log markers)

### Report Storage
- **Alibaba Cloud OSS** — the target service stores incident reports as JSON (`reports/YYYY-MM-DD/<id>.json`) via `/api/reports`
- **Local HTML report** — `core/report_generator.py` renders a self-contained report for the batch pipeline

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

The `MessageBus` carries the **negotiation exchange** between the two diagnostic agents (the phase order between agents is otherwise orchestrated directly by `ResQSwarm` in `main.py`):

| Type | Sender | Recipient | Description |
|------|--------|-----------|-------------|
| `hypotheses_shared` | Log Analyzer | Metric Monitor | Log Analyzer's hypotheses + evidence, shared for negotiation |
| `hypotheses_shared` | Metric Monitor | Log Analyzer | Metric Monitor's hypotheses + evidence, shared for negotiation |

The full message log (`bus.get_message_log()`) is attached to the incident result under `negotiation.message_log` for audit.

---

## Conflict Resolution Mechanism

ResQ resolves conflicts in two stages — **negotiation** (agents reconcile) then **arbitration** (weighted scoring):

**Stage 1 — Negotiation ([`core/negotiation.py`](core/negotiation.py)):** if the specialists disagree, each re-examines the incident with the other's evidence and revises (see [Negotiation Round](#negotiation-round-phase-15)). This is what lets a correct minority view survive.

**Stage 2 — Arbitration ([`core/consensus.py`](core/consensus.py)):** the Coordinator's `ConsensusEngine` scores the (revised) hypotheses:
1. Base confidence from the agent (0–1)
2. Evidence strength bonus (more grounded evidence = higher weight, capped)
3. Cross-agent confirmation bonus (+0.15 if both agents agree)
4. Select the top-scoring hypothesis; justify with an evidence summary

### Example Conflict Scenario (the ambiguous incident)

```
Log Analyzer:   "Memory leak / JVM heap exhaustion" (confidence high)
  Evidence: [heap climbing, GC pauses, OOM watchdog] — the LOUD signal in the logs

Metric Monitor: "Cache node failure → cache-miss storm overwhelming the DB"
  Evidence: [cache hit rate collapsed FIRST, memory bounded, pool not maxed]

Naive arbitration (no dialogue):
  → picks the high-confidence memory hypothesis  →  WRONG (memory is a symptom)

With negotiation (Phase 1.5):
  → Log Analyzer, shown the metric timeline, drops the memory-leak hypothesis
  → Coordinator arbitrates the revised set  →  correct cache root cause
```

This before/after is measured in [`docs/baseline_comparison.md`](docs/baseline_comparison.md): accuracy on this incident goes **0.0 (naive) → 1.0 (negotiated)**.

---

## Incident Detection Methods

### 1. Metric Polling (live TUI)
```python
# demo/resq_terminal.py polls the target service every ~1.5s
m = requests.get(f"{TARGET_URL}/api/metrics").json()
if m["error_rate"] > 8 or m["p99_latency_ms"] > 1500:
    trigger_investigation()
```

### 2. Incident fixture (batch)
```bash
python main.py --incident demo/sample_incidents/high_cpu.json
```

### 3. Live SLS logs (batch)
```bash
python main.py --sls-incident demo/sample_incidents/sls_incident.json
```

---

## Data Flow

```
1. Incident trigger (metric threshold crossed / incident fixture / SLS window)
   ↓
2. Phase 1 — Log Analyzer + Metric Monitor (parallel; each on its own data)
   ↓   (Log Analyzer also reads source code at error locations)
3. Phase 1.5 — Negotiation: if they disagree, agents exchange evidence and revise
   ↓
4. Phase 2 — Coordinator + ConsensusEngine arbitrate the revised hypotheses
   ↓   → verified root cause + action plan
5. Phase 3 — Runbook Executor generates/simulates remediation
   ↓
6. Phase 4 — Post-Mortem Writer generates report (grounded in actual data)
   ↓
7. Report uploaded to OSS  →  incident closed
```

> The investigator side (`integrations/`) is two modules: `qwen_client.py`
> (agent reasoning) and `alibaba_cloud.py` (SLS log reads). The deployed backend
> and its full SLS/OSS/ECS/CMS usage live in `target-service/`.

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
| **LLM** | Qwen Cloud (qwen-plus) | Agent reasoning, negotiation, analysis |
| **Terminal UI** | Textual + Rich | Live investigation display |
| **Compute** | Alibaba Cloud ECS | Hosts the target service |
| **Logs** | Alibaba Cloud SLS | Real-time log shipping + querying |
| **Storage** | Alibaba Cloud OSS | Incident report storage |
| **Monitoring** | Alibaba Cloud CMS | Host metrics |
| **Deployment** | Docker + Terraform | Infrastructure as code |

---

## Multi-Agent vs Single-Agent Comparison

### Measured results

ResQ ships a reproducible 3-way benchmark (`python main.py --baseline-comparison <incident.json>`) that runs the identical incident through a single-agent baseline, a naive multi-agent swarm, and the negotiated swarm. Average diagnostic accuracy over two incidents:

| Pipeline | Avg accuracy |
|----------|:---:|
| Single-agent | 0.75 |
| Multi-agent (naive arbitration) | 0.50 |
| **Multi-agent (negotiated)** | **1.00** |

The negotiated swarm is the only pipeline that solves both a clear-cut and an ambiguous incident — at a latency cost (~140s vs ~25s). Full methodology and per-metric numbers: [`docs/baseline_comparison.md`](docs/baseline_comparison.md).

### Why it wins

| Aspect | Single Agent | Multi-Agent (ResQ) |
|--------|-------------|-------------------|
| **Context window** | Must hold all signals in one prompt | Each agent focuses on one signal type |
| **Diagnostic depth** | Broad but shallow analysis | Deep, specialized analysis per agent |
| **Conflict resolution** | No internal debate | Agents surface conflicts and **negotiate** to resolve them |
| **Robustness on ambiguity** | Anchors on the loudest signal | Cross-references specialists; symptom ≠ cause |
| **Auditability** | Single narrative, hard to trace | Each agent's reasoning + the negotiation log are transparent |

---

## Alibaba Cloud Integration

The **target service** runs on Alibaba Cloud ECS and exercises four services through the official SDKs — this is the deployment proof. Real client code:

1. **SLS** (Simple Log Service) — real-time log shipping + query: [`target-service/integrations/sls_client.py`](target-service/integrations/sls_client.py) (`PutLogs`/`GetLogs`)
2. **OSS** (Object Storage) — report storage: [`target-service/integrations/oss_client.py`](target-service/integrations/oss_client.py)
3. **ECS** (Elastic Compute) — infrastructure context: [`target-service/integrations/ecs_client.py`](target-service/integrations/ecs_client.py) (`DescribeInstances`)
4. **CMS** (Cloud Monitor) — host metrics: [`target-service/integrations/cms_client.py`](target-service/integrations/cms_client.py) (`DescribeMetricLast`)

Infrastructure-as-code (VPC + ECS + SLS + OSS) is in [`target-service/deploy/terraform/`](target-service/deploy/terraform/); the deploy runbook is [`target-service/DEPLOY.md`](target-service/DEPLOY.md).

ResQ's own [`integrations/`](integrations/) layer is the investigator side: `qwen_client.py` (agent reasoning) and `alibaba_cloud.py` (SLS log fetching for `--sls-incident`).

---

## Configuration

Investigator side — configure via `.env`:

```bash
# Required — all agent reasoning
QWEN_API_KEY=your_key

# Optional — live SLS log reads (main.py --sls-incident)
ALIBABA_ACCESS_KEY_ID=your_key
ALIBABA_ACCESS_KEY_SECRET=your_secret
ALIBABA_REGION_ID=ap-southeast-3
SLS_PROJECT=your-project
SLS_LOGSTORE=your-logstore

# Optional — point the terminal at a remote target service
RESQ_TARGET_URL=http://<ecs-ip>:8000
```

See `.env.example` for the template. The **target service's** own configuration
(SLS/OSS/ECS/CMS) is documented in [`target-service/`](target-service/).
