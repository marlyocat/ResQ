# Baseline Comparison Results

This document tracks the comparison between single-agent and multi-agent (ResQ) incident response performance.

## Methodology

The same incident is processed through two pipelines:

1. **Single-Agent Baseline**: One Qwen model receives all logs + metrics in a single prompt and produces a diagnosis + remediation plan.
2. **ResQ Multi-Agent Swarm**: Four specialized agents (Log Analyzer, Metric Monitor, Runbook Executor, Post-Mortem Writer) plus a Coordinator work in parallel with structured conflict resolution.

## Metrics Tracked

| Metric | Description |
|--------|-------------|
| **Time to Diagnosis** | Time from incident trigger to root cause identification |
| **Diagnostic Accuracy** | Whether the correct root cause was identified |
| **Hypotheses Generated** | Number of distinct diagnostic hypotheses |
| **Evidence Quality** | Number of grounded (evidence-backed) claims vs. speculation |
| **Post-Mortem Completeness** | Coverage of timeline, root cause, impact, action items |

## Results

*Results will be populated after running `python main.py --baseline-comparison` with a valid QWEN_API_KEY.*

## Expected Outcomes

We expect ResQ to outperform the single-agent baseline on:
- **More hypotheses** (parallel specialization vs. single perspective)
- **Higher evidence quality** (each agent focuses on its data type)
- **Better conflict resolution** (structured arbitration vs. implicit trade-offs)
- **More complete post-mortems** (dedicated documentation agent)
