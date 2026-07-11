"""Conflict resolution and consensus mechanism for the Coordinator agent."""

from typing import List, Dict, Tuple
import logging

logger = logging.getLogger(__name__)


class ConsensusEngine:
    """Resolves conflicts between competing diagnostic hypotheses."""

    CROSS_AGENT_CONFIRMATION_BONUS = 0.15
    EVIDENCE_STRENGTH_THRESHOLD = 3

    def resolve(
        self,
        hypotheses_a: List[dict],
        hypotheses_b: List[dict]
    ) -> Tuple[dict, str]:
        """
        Resolve conflicts between hypotheses from two agents.

        Args:
            hypotheses_a: Hypotheses from first agent (e.g., Log Analyzer)
            hypotheses_b: Hypotheses from second agent (e.g., Metric Monitor)

        Returns:
            Tuple of (winning hypothesis, resolution justification)
        """
        # Score all hypotheses
        scored_a = self._score_hypotheses(hypotheses_a, "agent_a")
        scored_b = self._score_hypotheses(hypotheses_b, "agent_b")

        # Cross-reference for agreement
        all_hypotheses = scored_a + scored_b
        self._apply_cross_agent_bonus(all_hypotheses)

        # Select winner
        if not all_hypotheses:
            return self._no_hypothesis_fallback()

        winner = max(all_hypotheses, key=lambda h: h["adjusted_score"])
        justification = self._build_justification(winner, all_hypotheses)

        logger.info(f"Consensus reached: {winner['cause']} (score: {winner['adjusted_score']:.2f})")
        return winner, justification

    def _score_hypotheses(self, hypotheses: List[dict], source: str) -> List[dict]:
        """Score hypotheses from a single source."""
        scored = []
        for hyp in hypotheses:
            base_confidence = hyp.get("confidence", 0.0)
            evidence_count = len(hyp.get("evidence", []))
            evidence_bonus = min(0.1, evidence_count * 0.02)  # Cap at 0.1
            
            scored.append({
                **hyp,
                "source": source,
                "base_confidence": base_confidence,
                "evidence_bonus": evidence_bonus,
                "adjusted_score": base_confidence + evidence_bonus
            })
        return scored

    def _apply_cross_agent_bonus(self, all_hypotheses: List[dict]):
        """Apply bonus when both agents propose similar causes."""
        causes_a = {h["cause"].lower() for h in all_hypotheses if h["source"] == "agent_a"}
        causes_b = {h["cause"].lower() for h in all_hypotheses if h["source"] == "agent_b"}

        for hyp in all_hypotheses:
            cause_lower = hyp["cause"].lower()
            if (hyp["source"] == "agent_a" and cause_lower in causes_b) or \
               (hyp["source"] == "agent_b" and cause_lower in causes_a):
                hyp["adjusted_score"] += self.CROSS_AGENT_CONFIRMATION_BONUS
                hyp["cross_agent_confirmed"] = True

    def _no_hypothesis_fallback(self) -> Tuple[dict, str]:
        """Fallback when no hypotheses are provided."""
        fallback = {
            "cause": "Unknown - insufficient data for diagnosis",
            "confidence": 0.0,
            "adjusted_score": 0.0,
            "evidence": [],
            "severity": "unknown"
        }
        justification = "No diagnostic hypotheses provided by either agent. Manual investigation required."
        return fallback, justification

    def _build_justification(self, winner: dict, all_hypotheses: List[dict]) -> str:
        """Build a human-readable justification for the decision."""
        parts = [
            f"Selected root cause: {winner['cause']}",
            f"Confidence: {winner['adjusted_score']:.2f}",
            f"Evidence: {', '.join(winner.get('evidence', []))}",
        ]

        if winner.get("cross_agent_confirmed"):
            parts.append("✓ Confirmed by both Log Analyzer and Metric Monitor")

        # Add runner-up for context
        others = [h for h in all_hypotheses if h["cause"] != winner["cause"]]
        if others:
            runner_up = max(others, key=lambda h: h["adjusted_score"])
            parts.append(f"Runner-up: {runner_up['cause']} (score: {runner_up['adjusted_score']:.2f})")

        return " | ".join(parts)
