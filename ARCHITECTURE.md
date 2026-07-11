# ResQ Architecture

## System Overview

ResQ is a multi-agent incident response system where four specialized agents collaborate through a coordinator to diagnose, resolve, and document production incidents. Each agent has a distinct role, produces independent analysis, and participates in structured conflict resolution.

## Agent Roles

### 1. Log Analyzer Agent
**Responsibility:** Parse and analyze application/system logs to identify error patterns, anomalies, and potential root causes.

**Input:** Raw log data (structured/unstructured)
**Output:** List of diagnostic hypotheses with confidence scores

**Capabilities:**
- Pattern matching for known error signatures
- Temporal correlation of log events
- Error rate analysis
- Stack trace aggregation

**System Prompt Focus:** "You are a senior SRE analyzing production logs. Identify error patterns, unusual sequences, and potential root causes. Be specific about what you found and why it matters."

---

### 2. Metric Monitor Agent
**Responsibility:** Analyze system metrics (CPU, memory, latency, throughput, error rates) to detect anomalies and correlate with incident signals.

**Input:** Time-series metrics data
**Output:** List of diagnostic hypotheses with confidence scores

**Capabilities:**
- Anomaly detection on metric streams
- Cross-metric correlation (e.g., CPU spike + latency increase)
- Baseline comparison
- Capacity analysis

**System Prompt Focus:** "You are a monitoring specialist analyzing system metrics. Identify anomalous patterns, correlate across metrics, and propose root causes. Quantify your confidence with evidence."

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

**System Prompt Focus:** "You are an operations engineer executing remediation actions. Follow the approved plan, verify each step, and report results. Never execute unapproved actions."

---

### 4. Post-Mortem Writer Agent
**Responsibility:** Generate comprehensive incident documentation including timeline, root cause, impact, and action items.

**Input:** Full incident transcript from all agents
**Output:** Structured post-mortem document

**Capabilities:**
- Timeline reconstruction
- Root cause synthesis
- Impact assessment
- Actionable follow-up items

**System Prompt Focus:** "You are a technical writer creating an incident post-mortem. Be thorough, objective, and actionable. Include timeline, root cause, impact, and prevention measures."

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

**System Prompt Focus:** "You are an incident commander. Two specialists have provided different diagnoses. Compare their evidence, resolve conflicts, weight their confidence, and make a final call with justification."

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
        "severity": "high"
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

Metric Monitor: "CPU throttling due to runaway query (confidence: 0.75)"
  Evidence: [CPU spike at 95%, query latency 10x baseline]

Coordinator Resolution:
  → Both point to database issues, different root causes
  → Cross-check: connection exhaustion can cause CPU spike (waiting queries pile up)
  → Final: "Database connection pool exhaustion causing cascade (confidence: 0.85)"
  → Action: Increase pool size + add query timeout
```

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

### Measuring the Delta

Run the same incident through:
1. **Single-agent baseline:** One Qwen model prompted with all log + metric data
2. **ResQ swarm:** Full multi-agent pipeline

Compare:
- **MTTR** (time from incident trigger to resolution)
- **Diagnostic accuracy** (correct root cause identification)
- **Evidence quality** (number of grounded claims vs. hallucinations)
- **Completeness** (post-mortem thoroughness)

---

## Technology Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **LLM** | Qwen Cloud (qwen-turbo / qwen-plus) | Agent reasoning and generation |
| **Backend** | Alibaba Cloud ECS | API server and agent orchestration |
| **Log Storage** | Alibaba Cloud SLS (Log Service) | Log ingestion and querying |
| **Metrics** | Alibaba Cloud CMS (Cloud Monitor) | Time-series metrics |
| **Deployment** | Docker + Terraform | Infrastructure as code |
| **Testing** | pytest | Unit tests and baseline comparison |

---

## Data Flow

```
1. Incident trigger (alert/manual)
   ↓
2. Log Analyzer + Metric Monitor (parallel execution)
   ↓  (each produces hypotheses)
3. Coordinator receives both analyses
   ↓  (conflict resolution)
4. Coordinator produces action plan
   ↓
5. Runbook Executor applies fix
   ↓  (verifies result)
6. Post-Mortem Writer generates report
   ↓
7. Incident closed
```

---

## Alibaba Cloud Integration (Hackathon Requirement)

ResQ demonstrates Alibaba Cloud API usage through:

1. **ECS (Elastic Compute Service)** — Hosting the agent orchestration service
2. **SLS (Simple Log Service)** — Log ingestion and querying via API
3. **CMS (Cloud Monitor Service)** — Metrics retrieval via API
4. **ROS (Resource Orchestration Service)** — Infrastructure provisioning via Terraform

See `integrations/alibaba_cloud.py` for API usage proof.