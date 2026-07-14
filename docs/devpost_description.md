# ResQ — Devpost Submission

*(Copy-paste ready. Track 3: Agent Society.)*

## Inspiration
When production breaks at 3 a.m., diagnosis is a race across three data sources — logs, metrics, and source code — that no single on-call engineer holds in their head at once. A single LLM given "everything at once" tends to anchor on the loudest signal and misdiagnose. We wanted to show that a *team* of specialized agents that **divide the work, argue, and reconcile** beats a lone generalist — and to measure it.

## What it does
ResQ is a multi-agent incident-response system. When a monitored service degrades, five specialized Qwen-powered agents collaborate to find the root cause and produce a remediation plan and post-mortem — live, in a terminal UI.

- **Log Analyzer** and **Metric Monitor** diagnose in parallel, each from its own data source (task division).
- When they **disagree**, a **negotiation round** kicks in: each agent sees the other's hypotheses and evidence and re-examines the incident — separating root cause from downstream symptom, using which signal moved first — then revises. The dialogue runs over a message bus and is recorded.
- A **Coordinator** arbitrates the revised hypotheses (confidence + evidence + cross-agent confirmation) and commits to a root cause.
- A **Runbook Executor** proposes remediation and a **Post-Mortem Writer** documents the incident.

## How multi-agent beats single-agent (measured)
ResQ ships a reproducible 3-way benchmark (`python main.py --baseline-comparison <incident.json>`) that runs the identical incident through a single-agent baseline, a naive multi-agent swarm, and the negotiated swarm:

| Incident | Single | Multi (naive) | Multi (negotiated) |
|---|:---:|:---:|:---:|
| Clear-cut (DB pool exhaustion) | 0.5 | 1.0 | 1.0 |
| Ambiguous (cache failure disguised as memory leak) | 1.0 | 0.0 | 1.0 |
| **Avg diagnostic accuracy** | 0.75 | 0.50 | **1.00** |

On the ambiguous incident the logs scream "memory leak" while the metrics reveal a cache failure. Naive arbitration follows the loud signal and gets it wrong (0.0); the negotiation round flips it to correct (1.0). The negotiated swarm is the only pipeline that solves both incidents — at a latency cost we report honestly (~140s vs ~25s). This is the "measurable efficiency gain over single-agent baselines" the track asks for.

## How we built it
- **Qwen Cloud (qwen-plus)** for all agent reasoning, via the DashScope OpenAI-compatible API.
- **Alibaba Cloud** for the backend: the target service runs on **ECS** and uses **SLS** (real-time log shipping + query), **OSS** (report storage), and **CMS/ECS** (metrics + infrastructure context) through the official SDKs. IaC in Terraform.
- **Textual + Rich** for the live terminal UI, including a negotiation panel that shows the conflict and its resolution on screen.

## Challenges
Our first benchmark showed the naive swarm *losing* to a single agent on an ambiguous incident — a real finding, not a bug. It motivated the negotiation round: genuine agent-to-agent dialogue was what turned specialization into a measurable win. We kept the before/after in the results to show the effect honestly.

## What's next
Human-in-the-loop approval before remediation executes; more incident archetypes; and closing the loop by acting on the target service directly.

## Links
- **Repo:** https://github.com/marlyocat/ResQ (MIT license)
- **Alibaba Cloud deployment proof:** `target-service/integrations/` (SLS/OSS/ECS/CMS SDK clients) + `target-service/deploy/terraform/`
- **Benchmark methodology & results:** `docs/baseline_comparison.md`
- **Video:** [add link]
