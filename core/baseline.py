"""Single-agent baseline and multi-agent comparison harness.

This module exists to satisfy the Agent Society (Track 3) requirement of a
*measurable efficiency gain over a single-agent baseline*. It runs the same
incident through two pipelines and scores both on identical metrics:

    1. Single-Agent Baseline — ONE Qwen call receives all logs + metrics and
       must produce hypotheses, a root cause, an action plan, and a
       post-mortem in a single response.
    2. ResQ Multi-Agent Swarm — the five specialized agents + coordinator.

Both produce the same output shape, so the scorer is shared and the
comparison is apples-to-apples.
"""

import json
import re
import time
import logging
from typing import Dict, List, Optional

logger = logging.getLogger("resq.baseline")


# Sections a complete post-mortem should cover (used for completeness scoring).
POSTMORTEM_SECTIONS = [
    "summary",
    "timeline",
    "root cause",
    "impact",
    "resolution",
    "action item",
    "lessons learned",
]


SINGLE_AGENT_PROMPT = """You are a senior SRE. You are the ONLY responder to this
production incident — there is no team to delegate to. Given the logs and metrics
below, do the entire incident response yourself in one pass: form diagnostic
hypotheses, decide the root cause, write a remediation plan, and write a
post-mortem.

Return ONLY a JSON object in exactly this shape:
{
  "hypotheses": [
    {"cause": "...", "confidence": 0.0-1.0, "evidence": ["..."], "severity": "low|medium|high|critical"}
  ],
  "root_cause": {"cause": "...", "confidence": 0.0-1.0, "severity": "low|medium|high|critical"},
  "action_plan": {"steps": ["step 1", "step 2"]},
  "postmortem": "A full incident post-mortem covering: Summary, Timeline, Root Cause, Impact, Resolution, Action Items, and Lessons Learned."
}"""


def _extract_json(text: str) -> Optional[dict]:
    """Best-effort extraction of a JSON object from an LLM response."""
    if not text:
        return None
    cleaned = text.strip()
    if "```json" in cleaned:
        cleaned = cleaned.split("```json")[1].split("```")[0].strip()
    elif "```" in cleaned:
        cleaned = cleaned.split("```")[1].split("```")[0].strip()
    # Grab the outermost {...}
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        cleaned = cleaned[start:end + 1]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.warning("Baseline JSON parse failed: %s", e)
        return None


def _format_incident(incident_data: dict) -> str:
    """Render logs + metrics into a single prompt payload."""
    logs = incident_data.get("logs", "")
    metrics = incident_data.get("metrics", {})
    parts = ["PRODUCTION LOGS:", logs or "(none)", "", "SYSTEM METRICS:"]
    if isinstance(metrics, dict):
        for name, points in metrics.items():
            parts.append(f"### {name}")
            if isinstance(points, list):
                for dp in points:
                    parts.append(f"  {dp.get('timestamp', '')}: {dp.get('value', '')}")
            else:
                parts.append(f"  {points}")
    else:
        parts.append(str(metrics))
    return "\n".join(parts)


class SingleAgentBaseline:
    """One Qwen model does the whole incident response in a single call."""

    def __init__(self, qwen_client):
        self.qwen_client = qwen_client

    async def handle_incident(self, incident_data: dict) -> dict:
        user_input = (
            "Respond to the following production incident end to end.\n\n"
            + _format_incident(incident_data)
        )
        response = await self.qwen_client.analyze_with_context(
            system_prompt=SINGLE_AGENT_PROMPT,
            user_input=user_input,
        )
        parsed = _extract_json(response.get("raw_response", "")) or {}
        return {
            "hypotheses": parsed.get("hypotheses", []),
            "root_cause": parsed.get("root_cause", {}),
            "action_plan": parsed.get("action_plan", {}),
            "postmortem": {"postmortem": parsed.get("postmortem", "")},
            "raw_response": response.get("raw_response", ""),
        }


# ── Shared scoring ───────────────────────────────────────────────────────

def _hypotheses_from_swarm(results: dict) -> List[dict]:
    log_h = results.get("log_analyzer", {}).get("hypotheses", [])
    met_h = results.get("metric_monitor", {}).get("hypotheses", [])
    return list(log_h) + list(met_h)


def _grounded_evidence_count(hypotheses: List[dict]) -> int:
    """Count evidence-backed claims (a hypothesis with >=1 concrete evidence item)."""
    total = 0
    for h in hypotheses:
        for ev in h.get("evidence", []):
            if isinstance(ev, str) and ev.strip():
                total += 1
    return total


def _accuracy(root_cause_text: str, ground_truth: dict) -> float:
    """Fraction of ground-truth keywords present in the identified root cause."""
    keywords = [k.lower() for k in ground_truth.get("keywords", [])]
    if not keywords:
        return 0.0
    text = (root_cause_text or "").lower()
    hits = sum(1 for k in keywords if k in text)
    return round(hits / len(keywords), 3)


def _postmortem_completeness(postmortem_text: str) -> float:
    """Fraction of expected post-mortem sections present."""
    text = (postmortem_text or "").lower()
    hits = sum(1 for section in POSTMORTEM_SECTIONS if section in text)
    return round(hits / len(POSTMORTEM_SECTIONS), 3)


def score_run(name: str, output: dict, elapsed: float, ground_truth: dict) -> dict:
    """Score a single pipeline run on the five shared metrics.

    `output` must expose the common shape:
      - hypotheses (list) OR log_analyzer/metric_monitor hypotheses (swarm)
      - root_cause / coordinator.root_cause
      - postmortem.postmortem
    """
    # Hypotheses (swarm splits them across two agents)
    if "log_analyzer" in output or "metric_monitor" in output:
        hypotheses = _hypotheses_from_swarm(output)
        rc = output.get("coordinator", {}).get("root_cause", {})
        postmortem = output.get("postmortem", {}).get("postmortem", "")
    else:
        hypotheses = output.get("hypotheses", [])
        rc = output.get("root_cause", {})
        postmortem = output.get("postmortem", {}).get("postmortem", "")

    root_cause_text = rc.get("cause", "") if isinstance(rc, dict) else str(rc)

    return {
        "pipeline": name,
        "time_to_diagnosis_s": round(elapsed, 2),
        "diagnostic_accuracy": _accuracy(root_cause_text, ground_truth),
        "hypotheses_generated": len(hypotheses),
        "evidence_quality": _grounded_evidence_count(hypotheses),
        "postmortem_completeness": _postmortem_completeness(postmortem),
        "identified_root_cause": root_cause_text,
    }


METRIC_KEYS = [
    "diagnostic_accuracy",
    "hypotheses_generated",
    "evidence_quality",
    "postmortem_completeness",
    "time_to_diagnosis_s",
]


def build_comparison(single: dict, multi_naive: dict, multi_negotiated: dict,
                     ground_truth: dict) -> dict:
    """Assemble a 3-way comparison: single vs naive-arbitration vs negotiated swarm.

    Deltas are reported as (negotiated multi-agent − single agent), the headline
    efficiency-gain figure for the Track 3 write-up.
    """
    def delta(metric):
        return round(multi_negotiated[metric] - single[metric], 3)

    return {
        "ground_truth_root_cause": ground_truth.get("root_cause", "unknown"),
        "single_agent": single,
        "multi_agent_naive": multi_naive,
        "multi_agent_negotiated": multi_negotiated,
        "deltas": {k: delta(k) for k in METRIC_KEYS},
    }
