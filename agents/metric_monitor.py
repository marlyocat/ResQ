"""Metric Monitor Agent — analyzes system metrics for anomalies."""

from core.agent_base import AgentBase
from typing import List, Dict
import logging
import json

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a monitoring specialist analyzing system metrics to detect anomalies, correlate across metrics, and propose root causes.

Analyze the provided metrics data and return a list of diagnostic hypotheses. For each hypothesis:
- State the suspected cause clearly
- Provide a confidence score (0.0-1.0) with evidence
- List specific metric anomalies and their deviations from baseline
- Assess severity (low/medium/high/critical)

Focus on cross-metric correlations. A single metric spike is less significant than correlated spikes across related metrics.

Return your response as a JSON array of hypotheses in this exact format:
[
  {
    "cause": "Clear description of the root cause",
    "confidence": 0.85,
    "evidence": ["CPU at 95% (baseline: 40%)", "Memory at 89% (baseline: 55%)"],
    "severity": "high"
  }
]"""


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

        # Format metrics for the LLM
        metrics_text = self._format_metrics(metrics)
        user_input = f"Analyze the following system metrics and identify anomalous patterns and potential root causes:\n\n{metrics_text}"

        response = await self.qwen_client.analyze_with_context(
            system_prompt=self.system_prompt,
            user_input=user_input
        )

        hypotheses = self._parse_response(response.get("raw_response", ""))

        logger.info(f"Metric Monitor produced {len(hypotheses)} hypotheses")
        return {"hypotheses": hypotheses, "raw_analysis": response}

    def _format_metrics(self, metrics) -> str:
        """Format metrics data into a readable string for the LLM."""
        if isinstance(metrics, str):
            return metrics
        if isinstance(metrics, dict):
            lines = []
            for metric_name, data_points in metrics.items():
                lines.append(f"### {metric_name}")
                if isinstance(data_points, list):
                    for dp in data_points:
                        ts = dp.get("timestamp", "")
                        val = dp.get("value", "")
                        lines.append(f"  {ts}: {val}")
                else:
                    lines.append(f"  {data_points}")
            return "\n".join(lines)
        return str(metrics)

    def _parse_response(self, raw_text: str) -> List[Dict]:
        """Parse LLM response into structured hypotheses."""
        if not raw_text:
            return []

        # Try to parse as JSON array
        try:
            # Extract JSON array from response (handle markdown code blocks)
            cleaned = raw_text.strip()
            if "```json" in cleaned:
                cleaned = cleaned.split("```json")[1].split("```")[0].strip()
            elif "```" in cleaned:
                cleaned = cleaned.split("```")[1].split("```")[0].strip()

            hypotheses = json.loads(cleaned)
            if isinstance(hypotheses, list):
                # Validate structure
                valid_hypotheses = []
                for h in hypotheses:
                    if isinstance(h, dict) and "cause" in h:
                        valid_hypotheses.append({
                            "cause": h.get("cause", "Unknown"),
                            "confidence": float(h.get("confidence", 0.5)),
                            "evidence": h.get("evidence", []),
                            "severity": h.get("severity", "medium")
                        })
                if valid_hypotheses:
                    return valid_hypotheses
        except (json.JSONDecodeError, IndexError, ValueError) as e:
            logger.warning(f"Failed to parse Metric Monitor response as JSON: {e}")

        # Fallback: create a single hypothesis from the raw text
        return [
            {
                "cause": "Metric analysis completed (structured parsing failed, see raw response)",
                "confidence": 0.5,
                "evidence": ["See raw_analysis field for full LLM output"],
                "severity": "medium"
            }
        ]
