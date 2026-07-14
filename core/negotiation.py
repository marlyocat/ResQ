"""Inter-agent negotiation — the 'dialogue and negotiation' step for Track 3.

After the Log Analyzer and Metric Monitor produce independent hypotheses, they
often disagree (e.g. logs scream 'memory leak' while metrics say 'cache failure').
Naive arbitration just trusts whichever specialist is most confident, which lets a
loud-but-wrong hypothesis win. This module adds a genuine negotiation round: each
agent is shown the peer's hypotheses and evidence and asked to re-examine ALL the
evidence together — distinguishing root causes from downstream symptoms and using
the timeline of when each signal changed — then revise or defend its position.

The exchange is routed through the MessageBus so the dialogue is auditable.
"""

import json
import logging
from typing import List, Dict, Tuple, Optional

logger = logging.getLogger("resq.negotiation")


NEGOTIATION_SUFFIX = """

--- NEGOTIATION ROUND ---
A peer specialist analyzing a DIFFERENT data source has independently reached its
own conclusions. Re-examine the incident with BOTH sets of evidence in mind:

- A dramatic signal in your own data may be a downstream SYMPTOM, not the cause.
  (e.g. rising memory and GC pressure can be the *result* of a request queue
  backing up behind a slow dependency — not a memory leak.)
- Use the TIMELINE: the signal that moved FIRST is more likely the root cause;
  signals that moved afterward are more likely consequences.
- If the peer's evidence better explains the full picture, lower the confidence of
  your original hypothesis or replace it. If your evidence still holds, defend it.

Return the SAME JSON array format as before, with your REVISED hypotheses
(updated causes, confidence, evidence, severity)."""


def _top_cause(hypotheses: List[dict]) -> str:
    """Return the highest-confidence hypothesis's cause (lowercased)."""
    if not hypotheses:
        return ""
    top = max(hypotheses, key=lambda h: h.get("confidence", 0.0))
    return (top.get("cause", "") or "").lower()


_STOPWORDS = {
    # articles / prepositions / conjunctions
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "due", "by", "with", "from",
    # generic incident filler that shouldn't count as domain agreement
    "causing", "caused", "cause", "causes", "trigger", "triggers", "triggered",
    "triggering", "leading", "resulting", "results", "initiating", "cascading",
    "cascade", "massive", "sustained", "elevated", "increased", "severe",
    "service", "services", "error", "errors", "failure", "failures", "issue",
    "issues", "degradation", "degraded", "high", "low", "primary", "root",
}


def causes_agree(cause_a: str, cause_b: str) -> bool:
    """Heuristic: do two root-cause statements share a significant term?"""
    def sig(text):
        return {w for w in "".join(c if c.isalnum() else " " for c in text.lower()).split()
                if len(w) > 3 and w not in _STOPWORDS}
    a, b = sig(cause_a), sig(cause_b)
    return bool(a & b)


async def negotiate(agent, own_hypotheses: List[dict], peer_name: str,
                    peer_hypotheses: List[dict]) -> List[dict]:
    """Have `agent` reconsider its hypotheses in light of a peer's findings.

    Returns revised hypotheses (falls back to the originals if the LLM call or
    parse fails, so negotiation can never make things worse than not running).
    """
    if not peer_hypotheses:
        return own_hypotheses

    user_input = (
        f"YOUR CURRENT HYPOTHESES:\n{json.dumps(own_hypotheses, indent=2)}\n\n"
        f"PEER ({peer_name}) HYPOTHESES:\n{json.dumps(peer_hypotheses, indent=2)}\n\n"
        f"Re-examine all of the above together and return your revised hypotheses."
    )
    try:
        response = await agent.qwen_client.analyze_with_context(
            system_prompt=agent.system_prompt + NEGOTIATION_SUFFIX,
            user_input=user_input,
        )
        revised = agent._parse_response(response.get("raw_response", ""))
        if revised:
            logger.info("%s revised %d -> %d hypotheses after negotiation with %s",
                        agent.name, len(own_hypotheses), len(revised), peer_name)
            return revised
    except Exception as e:  # noqa: BLE001 - negotiation must never crash the pipeline
        logger.warning("Negotiation failed for %s: %s", agent.name, e)
    return own_hypotheses


async def run_negotiation_round(
    log_analyzer, metric_analyzer,
    log_hypotheses: List[dict], metric_hypotheses: List[dict],
    message_bus=None,
) -> Tuple[List[dict], List[dict], dict]:
    """Run one full negotiation round between the two diagnostic agents.

    Returns (revised_log_hyps, revised_metric_hyps, dialogue_record) where the
    dialogue_record documents whether there was a disagreement and how each side
    moved — useful for the TUI, the post-mortem, and the audit log.
    """
    import asyncio

    log_top_before = _top_cause(log_hypotheses)
    metric_top_before = _top_cause(metric_hypotheses)
    disagreement = bool(log_top_before and metric_top_before
                        and not causes_agree(log_top_before, metric_top_before))

    # Record the exchange on the message bus (auditable dialogue).
    if message_bus is not None:
        for name in (log_analyzer.name, metric_analyzer.name):
            message_bus.register_agent(name)
        await message_bus.send(log_analyzer.create_message(
            recipient=metric_analyzer.name, message_type="hypotheses_shared",
            payload={"hypotheses": log_hypotheses}))
        await message_bus.send(metric_analyzer.create_message(
            recipient=log_analyzer.name, message_type="hypotheses_shared",
            payload={"hypotheses": metric_hypotheses}))

    # Both agents reconsider concurrently.
    revised_log, revised_metric = await asyncio.gather(
        negotiate(log_analyzer, log_hypotheses, metric_analyzer.name, metric_hypotheses),
        negotiate(metric_analyzer, metric_hypotheses, log_analyzer.name, log_hypotheses),
    )

    log_top_after = _top_cause(revised_log)
    metric_top_after = _top_cause(revised_metric)
    converged = bool(log_top_after and metric_top_after
                     and causes_agree(log_top_after, metric_top_after))

    dialogue = {
        "disagreement_detected": disagreement,
        "converged_after_negotiation": converged,
        "log_analyzer": {"before": log_top_before, "after": log_top_after},
        "metric_monitor": {"before": metric_top_before, "after": metric_top_after},
    }
    logger.info("Negotiation: disagreement=%s converged=%s", disagreement, converged)
    return revised_log, revised_metric, dialogue
