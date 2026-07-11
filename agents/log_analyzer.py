"""Log Analyzer Agent — parses and analyzes logs for incident diagnosis."""

from core.agent_base import AgentBase
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a senior SRE analyzing production logs to identify error patterns, unusual sequences, and potential root causes. 

Analyze the provided logs and return a list of diagnostic hypotheses. For each hypothesis:
- State the suspected cause clearly
- Provide a confidence score (0.0-1.0)
- List specific evidence from the logs
- Assess severity (low/medium/high/critical)

Be specific and evidence-based. Do not speculate without log support."""


class LogAnalyzer(AgentBase):
    """Agent responsible for log analysis and pattern detection."""

    def __init__(self, qwen_client):
        super().__init__(
            name="log_analyzer",
            role="log_analysis",
            system_prompt=SYSTEM_PROMPT
        )
        self.qwen_client = qwen_client

    async def analyze(self, incident_data: dict) -> dict:
        """
        Analyze log data and produce diagnostic hypotheses.

        Args:
            incident_data: Must contain 'logs' key with log data

        Returns:
            Dictionary with 'hypotheses' list
        """
        logs = incident_data.get("logs", "")
        if not logs:
            logger.warning("No log data provided to Log Analyzer")
            return {"hypotheses": []}

        user_input = f"Analyze the following production logs and identify potential root causes:\n\n{logs}"

        response = await self.qwen_client.analyze_with_context(
            system_prompt=self.system_prompt,
            user_input=user_input
        )

        # Parse the response into hypotheses
        # In production, use structured output or JSON parsing
        hypotheses = self._parse_response(response.get("raw_response", ""))
        
        logger.info(f"Log Analyzer produced {len(hypotheses)} hypotheses")
        return {"hypotheses": hypotheses, "raw_analysis": response}

    def _parse_response(self, raw_text: str) -> List[Dict]:
        """Parse LLM response into structured hypotheses."""
        # Placeholder parser — in production, use JSON schema or robust parsing
        if not raw_text:
            return []
        
        # Simple extraction for demo purposes
        return [
            {
                "cause": "Extracted from LLM response",
                "confidence": 0.75,
                "evidence": ["Evidence point 1", "Evidence point 2"],
                "severity": "high"
            }
        ]
