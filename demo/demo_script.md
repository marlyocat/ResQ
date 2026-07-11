# ResQ Demo Script (3-minute video)

## Scene 1: Introduction (0:00-0:20)
- **Narration**: "ResQ is a multi-agent incident response swarm. Instead of one AI trying to diagnose everything, ResQ depages four specialized agents that collaborate to find the root cause faster."
- **Show**: Architecture diagram from README

## Scene 2: The Incident (0:20-0:40)
- **Narration**: "Here's a real-world scenario: CPU spikes, connection pool exhaustion, cascading failures. Let's see how ResQ handles it."
- **Show**: `demo/sample_incidents/high_cpu.json` — highlight the log entries and metric spikes

## Scene 3: Parallel Diagnosis (0:40-1:20)
- **Narration**: "Two agents work in parallel. The Log Analyzer scans error patterns. The Metric Monitor correlates anomalies. They each produce independent hypotheses — no shared context, no cross-contamination."
- **Show**: Terminal output running `python main.py --incident demo/sample_incidents/high_cpu.json`
- **Highlight**: Both agents produce their hypotheses independently

## Scene 4: Conflict Resolution (1:20-1:50)
- **Narration**: "What if they disagree? The Coordinator agent compares evidence, applies cross-agent confirmation bonuses, and makes a final call with full justification. This is the key innovation — structured debate, not a single agent guessing."
- **Show**: Coordinator output showing arbitration decision and justification

## Scene 5: Remediation & Documentation (1:50-2:20)
- **Narration**: "Once the root cause is verified, the Runbook Executor applies the fix, and the Post-Mortem Writer generates comprehensive documentation — timeline, root cause, impact, action items."
- **Show**: Post-mortem output

## Scene 6: Baseline Comparison (2:20-3:00)
- **Narration**: "Here's the critical comparison. The same incident run through a single agent vs. ResQ's multi-agent swarm. ResQ produces more hypotheses, higher evidence quality, and more complete documentation."
- **Show**: `python main.py --baseline-comparison` output with comparison table
- **Close**: "ResQ — proving that multi-agent collaboration outperforms single-agent AI. Built for the Qwen Cloud Global AI Hackathon."
