# ResQ — Multi-Agent Incident Response System

An agentic incident response system where specialized AI agents collaborate to diagnose, resolve, and document production incidents. Built for the **1st Qwen Cloud Global AI Hackathon** (Agent Society Track).

## Overview

ResQ connects to your existing infrastructure (logs, metrics, source code, databases) and automatically investigates incidents when they occur. Five specialized agents work in parallel to identify root causes and generate actionable remediation plans.

**Key Features:**
- **Real-time terminal UI** — Watch agents investigate live
- **5 incident scenarios** — DB pool exhaustion, cache failure, queue failure, memory leak, external API failure
- **Organic AI analysis** — Qwen API analyzes actual logs, metrics, and source code (no hardcoded responses)
- **Source code investigation** — Agents read your actual codebase at error locations
- **Infrastructure probes** — Check Redis, PostgreSQL, Kafka, RabbitMQ health
- **OSS report storage** — Incident reports automatically uploaded to Alibaba Cloud OSS
- **Alert webhooks** — Receive alerts from Grafana, PagerDuty, etc.

## Architecture

```
Your Infrastructure          ResQ Agents              Output
─────────────────          ─────────────          ──────────
SLS Logs          ──────▶  Log Analyzer           ┐
Prometheus        ──────▶  Metric Monitor         │
GitHub/Local Repo ──────▶  Code Indexer           ├─▶ Terminal UI
Redis/PostgreSQL  ──────▶  Infrastructure Probes  │    (live)
Alert Webhook     ──────▶  Coordinator            │
                         ─────────────          │
                         Runbook Executor         │
                         Post-Mortem Writer       ┘
                                                      └─▶ OSS Storage
                                                          (reports)
```

## Quick Start

### Prerequisites

- Python 3.10+
- Qwen Cloud API key ([get one here](https://www.qwencloud.com/api-keys))
- Alibaba Cloud account ([free trial](https://www.alibabacloud.com/free-trial))

### Setup

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/ResQ.git
cd ResQ

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your credentials
```

### Run Demo Scenarios

ResQ includes 5 built-in scenarios for demonstration:

```bash
# Scenario 1: Database Connection Pool Exhaustion
python demo/run_demo.py --scenario 1

# Scenario 2: Cache Failure
python demo/run_demo.py --scenario 2

# Scenario 3: Message Queue Failure
python demo/run_demo.py --scenario 3

# Scenario 4: Memory Leak
python demo/run_demo.py --scenario 4

# Scenario 5: External API Dependency Failure
python demo/run_demo.py --scenario 5
```

Each scenario runs a live incident investigation with real Qwen API analysis. Press `q` to exit the terminal UI.

### Production Integration

To connect ResQ to your real infrastructure, configure `.env`:

```bash
# Logs (Alibaba Cloud SLS)
SLS_PROJECT=your-project
SLS_LOGSTORE=your-logstore

# Metrics (Prometheus)
PROMETHEUS_URL=http://your-prometheus:9090

# Source Code
SOURCE_LOCAL_PATH=/path/to/your/app
# OR
SOURCE_GITHUB_URL=https://github.com/yourorg/yourapp

# Infrastructure
REDIS_URL=redis://your-redis:6379
DATABASE_URL=postgresql://user:pass@host:5432/db

# Report Storage (Alibaba Cloud OSS)
OSS_ENDPOINT=https://oss-cn-hangzhou.aliyuncs.com
OSS_BUCKET_NAME=resq-reports

# Alert Webhook
RESQ_WEBHOOK_PORT=5001
```

See `integrations/README.md` for detailed integration documentation.

## Project Structure

```
ResQ/
├── agents/                    # Agent implementations
│   ├── log_analyzer.py        # Analyzes logs for error patterns
│   ├── metric_monitor.py      # Analyzes metrics for anomalies
│   ├── coordinator.py         # Arbitrates between hypotheses
│   ├── runbook_executor.py    # Executes remediation steps
│   └── postmortem_writer.py   # Generates incident reports
├── core/                      # Shared infrastructure
│   ├── agent_base.py          # Base agent class
│   ├── communication.py       # Message bus
│   └── consensus.py           # Conflict resolution
├── integrations/              # Real infrastructure connectors
│   ├── prometheus_client.py   # Prometheus metrics
│   ├── source_indexer.py      # Source code indexing
│   ├── infrastructure_probes.py # Redis/DB/Kafka health
│   ├── alert_webhook.py       # Alert receiver
│   ├── oss_client.py          # OSS report storage
│   ├── config.py              # Configuration management
│   └── README.md              # Integration docs
├── demo/                      # Demo scenarios
│   ├── run_demo.py            # Demo runner
│   ├── resq_terminal.py       # Terminal UI
│   ├── load_sim.py            # Load simulator
│   └── queue_simulator.py     # Queue failure simulation
├── target/                    # Demo Flask app
│   └── app.py                 # Simulated production service
├── docs/                      # Documentation
│   ├── demo_scenarios.md      # Scenario descriptions
│   └── baseline_comparison.md # Single vs multi-agent comparison
├── tests/                     # Test suite
├── deploy/                    # Deployment configs
│   ├── docker/                # Docker deployment
│   └── terraform/             # Alibaba Cloud Terraform
├── .env.example               # Environment template
├── requirements.txt           # Python dependencies
└── README.md                  # This file
```

## How It Works

### Incident Detection

ResQ detects incidents via:
1. **Alert webhooks** — Grafana/PagerDuty send alerts to `/webhook/alert`
2. **Metric polling** — Periodically check Prometheus for anomalies
3. **Log analysis** — Monitor SLS for error spikes

### Agent Investigation

When an incident is detected:

1. **Log Analyzer** — Queries SLS for error logs, extracts stack traces, identifies error patterns
2. **Metric Monitor** — Queries Prometheus for metric anomalies (error rate, latency, CPU)
3. **Code Indexer** — Reads source code at error locations identified in logs
4. **Infrastructure Probes** — Checks Redis, PostgreSQL, Kafka health
5. **Coordinator** — Arbitrates between agent findings, determines root cause
6. **Runbook Executor** — Generates remediation steps
7. **Post-Mortem Writer** — Generates comprehensive incident report

### Report Storage

After investigation completes:
- Report uploaded to OSS: `incidents/YYYY-MM-DD/incident_id.json`
- Available for retrieval and historical analysis

## 5 Demo Scenarios

| # | Scenario | What It Demonstrates |
|---|----------|---------------------|
| 1 | **DB Connection Pool Exhaustion** | Resource exhaustion, connection timeouts |
| 2 | **Cache Failure** | Cache miss storm, DB overload |
| 3 | **Message Queue Failure** | Distributed service communication breakdown |
| 4 | **Memory Leak** | Gradual degradation, OOM kill |
| 5 | **External API Failure** | Third-party dependency, cascading timeouts |

Each scenario produces distinct logs and metrics. Qwen API analyzes the actual data to produce unique root cause analysis — no hardcoded responses.

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

## Free Tier Availability

All required services are available on Alibaba Cloud free tier:

- **Qwen API** — Free credits for hackathon participants
- **SLS** — 500MB/day log ingestion
- **OSS** — 5GB storage
- **ECS/RDS/Redis/Kafka** — 3-month free trial for new users
- **Prometheus/Grafana** — Open source, run locally

## Hackathon Submission

- **Track:** Agent Society (Track 3)
- **Demo Video:** [YouTube link]
- **Architecture Diagram:** See above
- **Alibaba Cloud Integration:** See `integrations/` directory

## License

MIT License — see [LICENSE](LICENSE)
