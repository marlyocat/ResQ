"""Runbook Executor Agent — executes verified remediation actions."""

from core.agent_base import AgentBase
from typing import Dict
import logging

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an operations engineer executing remediation actions during an incident.

Given an approved action plan from the Incident Commander (Coordinator):
1. Execute each step in order
2. Verify the result of each step
3. Report success or failure for each step
4. If a step fails, report the error and suggest alternatives
5. Never execute actions not in the approved plan

Safety is paramount. Always include verification after each action."""


class RunbookExecutor(AgentBase):
    """Agent responsible for executing remediation actions."""

    def __init__(self, qwen_client):
        super().__init__(
            name="runbook_executor",
            role="remediation",
            system_prompt=SYSTEM_PROMPT
        )
        self.qwen_client = qwen_client
        self.execution_log = []

    async def execute(self, action_plan: dict) -> dict:
        """
        Execute the approved action plan.

        Args:
            action_plan: Approved remediation steps from Coordinator

        Returns:
            Dictionary with execution results
        """
        steps = action_plan.get("steps", "")
        if not steps:
            logger.warning("No action plan provided to Runbook Executor")
            return {"status": "skipped", "reason": "empty action plan"}

        # Simulate execution (in production, would execute actual commands)
        execution_results = await self._simulate_execution(steps)
        self.execution_log.append({
            "action_plan": steps,
            "results": execution_results
        })

        return {
            "status": execution_results.get("overall_status", "unknown"),
            "steps_executed": execution_results,
            "verified": execution_results.get("verified", False)
        }

    async def _simulate_execution(self, steps: str) -> dict:
        """Simulate execution of remediation steps."""
        # In production, this would execute actual system commands
        # For now, use LLM to simulate realistic execution
        user_input = f"Simulate the execution of the following remediation steps and report results:\n\n{steps}"

        response = await self.qwen_client.analyze_with_context(
            system_prompt=self.system_prompt,
            user_input=user_input
        )

        return {
            "overall_status": "completed",
            "execution_detail": response.get("raw_response", ""),
            "verified": True
        }

    async def analyze(self, incident_data: dict) -> dict:
        """Runbook Executor does not analyze — it executes via execute()."""
        return {"error": "RunbookExecutor uses execute(), not analyze()"}
