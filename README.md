# ResQ — Multi-Agent Incident Response Swarm

An agentic incident response system where specialized agents collaborate to diagnose, resolve, and document production incidents. Built for the **1st Qwen Cloud Global AI Hackathon** (Agent Society Track).

## Overview

ResQ replaces a single overloaded AI with a swarm of 5 specialized agents that collaborate through structured roles:

- **Parallel diagnosis** — Log Analyzer and Metric Monitor independently investigate signals
- **Structured arbitration** — Coordinator resolves competing root cause hypotheses
- **Automated remediation** — Runbook Executor applies verified fixes
- **Auto-documentation** — Post-Mortem Writer generates incident reports

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        INCIDENT TRIGGER                          │
│              (Alert, anomaly, manual invocation)                 │
└────────────────────────────┬────────────────────────────────────┘
                             │
              ┌──────────────┴──────────────┐
              ▼                             ▼
┌───────────────────────┐     ┌───────────────────────────┐
│    Log Analyzer       │     │     Metric Monitor        │
│  (pattern detection)  │     │  (anomaly correlation)    │
└───────────┬───────────┘     └─────────────┬─────────────┘
            │  diagnosis hypotheses         │  diagnosis hypotheses
            └──────────────┬────────────────┘
                           ▼
              ┌────────────────────────┐
              │     Coordinator        │
              │ (conflict resolution,  │
              │  root cause arbitration)│
              └────────────┬───────────┘
                           │ verified root cause + action plan
                           ▼
              ┌────────────────────────┐
              │   Runbook Executor     │
              │ (automated remediation)│
              └────────────┬───────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │  Post-Mortem Writer    │
              │ (incident documentation)│
              └────────────────────────┘

All agents powered by Qwen Cloud APIs
Backend deployed on Alibaba Cloud (ECS + Log Service + SLS)
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

# Configure API keys
cp .env.example .env
# Edit .env with your Qwen Cloud API key and Alibaba Cloud credentials
```

### Run

```bash
# Run a sample incident with static (pre-loaded) logs
python main.py --incident demo/sample_incidents/high_cpu.json

# Run a live incident fetching logs from Alibaba Cloud SLS
python main.py --sls-incident demo/sample_incidents/sls_incident.json

# Run tests
pytest tests/
```

### Running with Live SLS Logs

To fetch real logs from Alibaba Cloud SLS:

1. Install the SLS SDK: `pip install aliyun-log-python-sdk`
2. Set your Alibaba Cloud credentials in `.env`:
   ```
   ALIBABA_ACCESS_KEY_ID=your_key
   ALIBABA_ACCESS_KEY_SECRET=your_secret
   ALIBABA_REGION_ID=cn-hangzhou  # or your region
   ```
3. Create an SLS project and logstore, then configure your apps to ship logs there
4. Update `demo/sample_incidents/sls_incident.json` with your project/logstore names
5. Run: `python main.py --sls-incident demo/sample_incidents/sls_incident.json`

## Project Structure

```
ResQ/
├── agents/              # Specialized agent implementations
│   ├── log_analyzer.py
│   ├── metric_monitor.py
│   ├── runbook_executor.py
│   ├── postmortem_writer.py
│   └── coordinator.py
├── core/                # Shared infrastructure
│   ├── agent_base.py
│   ├── communication.py
│   └── consensus.py
├── integrations/        # External service connections
│   ├── qwen_client.py      # Qwen Cloud API integration
│   └── alibaba_cloud.py    # Alibaba Cloud deployment proof
├── tests/               # Test suite for consensus and communication
├── demo/                # Demo materials and sample incidents
├── deploy/              # Alibaba Cloud deployment configs
├── docs/                # Additional documentation
├── ARCHITECTURE.md      # Detailed system design
├── README.md            # This file
└── LICENSE              # MIT License
```

## Hackathon Submission

- **Track:** Agent Society (Track 3)
- **Demo Video:** [YouTube link]
- **Architecture Diagram:** See above + `ARCHITECTURE.md`
- **Alibaba Cloud Deployment Proof:** See `integrations/alibaba_cloud.py`

## How Multi-Agent Collaboration Works

| Agent | Responsibility | What makes it effective |
|-------|---------------|------------------------|
| **Log Analyzer** | Parses production logs, identifies error patterns | Focused on one data source — no metric noise to distract it |
| **Metric Monitor** | Analyzes time-series metrics for anomalies | Cross-metric correlation — catches cascading failures early |
| **Coordinator** | Arbitrates between competing hypotheses | Structured conflict resolution with evidence scoring — not just picking the loudest voice |
| **Runbook Executor** | Executes verified remediation actions | Safety-first — only runs approved actions, verifies each step |
| **Post-Mortem Writer** | Generates incident documentation | Dedicated to thoroughness — timeline, root cause, impact, action items |

**Why this beats a single agent:** Each agent focuses on one signal type with a tailored system prompt. Two independent diagnoses surface more hypotheses. The Coordinator forces structured debate instead of implicit trade-offs. And the output is auditable — you can see exactly which agent said what.

## License

MIT License — see [LICENSE](LICENSE)