"""Log Analyzer Agent — parses and analyzes logs for incident diagnosis."""

from core.agent_base import AgentBase
from typing import List, Dict, Optional
from datetime import datetime
import logging
import json

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a senior SRE analyzing production logs to identify error patterns, unusual sequences, and potential root causes.

Analyze the provided logs and return a list of diagnostic hypotheses. For each hypothesis:
- State the suspected cause clearly
- Provide a confidence score (0.0-1.0)
- List specific evidence from the logs
- Assess severity (low/medium/high/critical)

Be specific and evidence-based. Do not speculate without log support.

Return your response as a JSON array of hypotheses in this exact format:
[
  {
    "cause": "Clear description of the root cause",
    "confidence": 0.85,
    "evidence": ["specific log line or pattern", "another evidence point"],
    "severity": "high"
  }
]"""


class LogAnalyzer(AgentBase):
    """Agent responsible for log analysis and pattern detection."""

    def __init__(self, qwen_client, sls_client=None):
        super().__init__(
            name="log_analyzer",
            role="log_analysis",
            system_prompt=SYSTEM_PROMPT
        )
        self.qwen_client = qwen_client
        self.sls_client = sls_client  # Optional: Alibaba Cloud SLS client

    async def analyze(self, incident_data: dict) -> dict:
        """
        Analyze log data and produce diagnostic hypotheses.

        Supports two modes:
        1. SLS mode: Fetch logs from Alibaba Cloud SLS (preferred for production)
        2. Static mode: Use pre-loaded logs from incident_data (for demos/testing)

        Args:
            incident_data: Must contain one of:
                - 'sls_config': Dict with SLS project, logstore, query, etc.
                - 'logs': Raw log string (fallback for demos)

        Returns:
            Dictionary with 'hypotheses' list
        """
        logs = await self._get_logs(incident_data)
        if not logs:
            logger.warning("No log data provided to Log Analyzer")
            return {"hypotheses": []}

        # Format logs for the LLM
        if isinstance(logs, list):
            # SLS mode: format structured log entries
            log_text = self._format_sls_logs(logs)
        else:
            # Static mode: raw log string
            log_text = logs

        user_input = f"Analyze the following production logs and identify potential root causes:\n\n{log_text}"

        response = await self.qwen_client.analyze_with_context(
            system_prompt=self.system_prompt,
            user_input=user_input
        )

        # Parse the response into structured hypotheses
        hypotheses = self._parse_response(response.get("raw_response", ""))

        logger.info(f"Log Analyzer produced {len(hypotheses)} hypotheses")
        return {
            "hypotheses": hypotheses,
            "raw_analysis": response,
            "log_source": "sls" if isinstance(logs, list) else "static"
        }

    async def _get_logs(self, incident_data: dict):
        """
        Get logs from SLS or static incident data.

        Priority: SLS > static logs > empty
        """
        # Try SLS mode first if SLS client is available
        if self.sls_client:
            sls_config = incident_data.get("sls_config")
            if sls_config:
                logger.info(f"Fetching logs from SLS: project={sls_config.get('project')}")
                return await self._fetch_logs_from_sls(incident_data, sls_config)

        # Fallback to static logs
        return incident_data.get("logs", "")

    async def _fetch_logs_from_sls(self, incident_data: dict, sls_config: dict):
        """Fetch logs from Alibaba Cloud SLS based on incident context."""
        project = sls_config.get("project", "")
        logstore = sls_config.get("logstore", "")
        query = sls_config.get("query", "*")

        # Determine time window from incident data
        incident_time_str = incident_data.get("timestamp", "")
        if incident_time_str:
            incident_time = datetime.fromisoformat(incident_time_str.replace("Z", "+00:00"))
            incident_time = incident_time.replace(tzinfo=None)  # Make naive for utcfromtimestamp
        else:
            incident_time = datetime.utcnow()

        lookback_minutes = sls_config.get("lookback_minutes", 30)

        # Use the high-level convenience method
        return await self.sls_client.fetch_logs_for_incident(
            project=project,
            logstore=logstore,
            incident_time=incident_time,
            services=sls_config.get("services"),
            levels=sls_config.get("levels", ["ERROR", "CRITICAL"]),
            lookback_minutes=lookback_minutes
        )

    def _format_sls_logs(self, logs: List[dict]) -> str:
        """Format structured SLS log entries into a readable string for the LLM."""
        if not logs:
            return "(No logs returned from SLS)"

        lines = []
        lines.append(f"[SLS Log Query Results - {len(logs)} entries]")
        lines.append("=" * 80)

        for entry in logs:
            # Build a formatted log line from SLS key-value pairs
            ts = entry.get("timestamp", "unknown")
            level = entry.get("level", entry.get("__level__", "INFO"))
            service = entry.get("service", entry.get("__source__", "unknown"))
            message = entry.get("message", entry.get("msg", str(entry)))

            lines.append(f"{ts} [{level}] {service}: {message}")

        lines.append("=" * 80)
        return "\n".join(lines)

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
            logger.warning(f"Failed to parse LLM response as JSON: {e}")

        # Fallback: create a single hypothesis from the raw text
        return [
            {
                "cause": "LLM analysis completed (structured parsing failed, see raw response)",
                "confidence": 0.5,
                "evidence": ["See raw_analysis field for full LLM output"],
                "severity": "medium"
            }
        ]
