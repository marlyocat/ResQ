"""Coordinator Agent — arbitrates between competing hypotheses and produces action plans."""

from core.agent_base import AgentBase
from core.consensus import ConsensusEngine
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an incident commander coordinating between two specialist agents: a Log Analyzer and a Metric Monitor.

Each specialist has provided their independent diagnosis. Your job:
1. Compare their evidence and hypotheses
2. Identify areas of agreement and conflict
3. Resolve conflicts using evidence quality and cross-agent confirmation
4. Make a final root cause determination with clear justification
5. Produce an actionable remediation plan

Be decisive. An incident cannot proceed without a clear action plan."""


class Coordinator(AgentBase):
    """Agent responsible for conflict resolution and action plan generation."""

    def __init__(self, qwen_client):
        super().__init__(
            name="coordinator",
            role="coordination",
            system_prompt=SYSTEM_PROMPT
        )
        self.qwen_client = qwen_client
        self.consensus_engine = ConsensusEngine()

    async def arbitrate(
        self,
        log_hypotheses: List[dict],
        metric_hypotheses: List[dict]
    ) -> dict:
        """
        Resolve conflicts between Log Analyzer and Metric Monitor hypotheses.

        Args:
            log_hypotheses: Hypotheses from Log Analyzer
            metric_hypotheses: Hypotheses from Metric Monitor

        Returns:
            Dictionary with winning hypothesis, justification, and action plan
        """
        # Run consensus engine
        winner, justification = self.consensus_engine.resolve(
            log_hypotheses, metric_hypotheses
        )

        # Generate action plan via LLM
        action_plan = await self._generate_action_plan(winner)

        return {
            "root_cause": winner,
            "justification": justification,
            "action_plan": action_plan
        }

    async def _generate_action_plan(self, root_cause: dict) -> dict:
        """Generate a concrete action plan based on the resolved root cause."""
        user_input = (
            f"Based on the following root cause analysis, generate a step-by-step "
            f"remediation plan:\n\n"
            f"Root Cause: {root_cause.get('cause', 'Unknown')}\n"
            f"Evidence: {', '.join(root_cause.get('evidence', []))}\n"
            f"Severity: {root_cause.get('severity', 'unknown')}\n\n"
            f"Include: immediate actions, verification steps, and rollback plan."
        )

        response = await self.qwen_client.analyze_with_context(
            system_prompt=self.system_prompt,
            user_input=user_input
        )

        return {
            "steps": response.get("raw_response", "No action plan generated"),
            "verified": False
        }

    async def analyze(self, incident_data: dict) -> dict:
        """Coordinator does not analyze raw data — it arbitrates between agents."""
        return {"error": "Coordinator uses arbitrate(), not analyze()"}
