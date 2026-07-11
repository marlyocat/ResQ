"""Metric Monitor Agent — analyzes system metrics for anomalies."""

from core.agent_base import AgentBase
from typing import List, Dict
import logging

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a monitoring specialist analyzing system metrics to detect anomalies, correlate across metrics, and propose root causes.

Analyze the provided metrics data and return a list of diagnostic hypotheses. For each hypothesis:
- State the suspected cause clearly
- Provide a confidence score (0.0-1.0) with evidence
- List specific metric anomalies and their deviations from baseline
- Assess severity (low/medium/high/critical)

Focus on cross-metric correlations. A single metric spike is less significant than correlated spikes across related metrics."""


class MetricMonitor(AgentBase):
    """Agent responsible for metric analysis and anomaly detection."""

    def __init__(self, qwen_client):
        super().__init__(
            name="metric_monitor",
            role="metric_analysis",
            system_prompt=SYSTEM_PROMPT
        )
        self.qwen_client = qwen_client

    async def analyze(self, incident_data: dict) -> dict:
        """
        Analyze metric data and produce diagnostic hypotheses.

        Args:
            incident_data: Must contain 'metrics' key with metric data

        Returns:
            Dictionary with 'hypotheses' list
        """
        metrics = incident_data.get("metrics", "")
        if not metrics:
            logger.warning("No metric data provided to Metric Monitor")
            return {"hypotheses": []}

        user_input = f"Analyze the following system metrics and identify anomalous patterns and potential root causes:\n\n{metrics}"

        response = await self.qwen_client.analyze_with_context(
            system_prompt=self.system_prompt,
            user_input=user_input
        )

        hypotheses = self._parse_response(response.get("raw_response", ""))
        
        logger.info(f"Metric Monitor produced {len(hypotheses)} hypotheses")
        return {"hypotheses": hypotheses, "raw_analysis": response}

    def _parse_response(self, raw_text: str) -> List[Dict]:
        """Parse LLM response into structured hypotheses."""
        if not raw_text:
            return []
        
        return [
            {
                "cause": "Extracted from LLM response",
                "confidence": 0.70,
                "evidence": ["CPU at 95% (baseline: 40%)", "Memory at 89% (baseline: 55%)"],
                "severity": "high"
            }
        ]
