"""Post-Mortem Writer Agent — generates comprehensive incident documentation."""

from core.agent_base import AgentBase
from typing import Dict
import logging

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a technical writer creating a comprehensive incident post-mortem.

Given the full incident transcript (all agent analyses, decisions, and execution results), produce a structured post-mortem document including:

1. **Incident Summary** — Brief description of what happened
2. **Timeline** — Chronological sequence of events
3. **Root Cause** — Final determination with evidence
4. **Impact** — Affected systems, users, and duration
5. **Resolution** — Actions taken and their effectiveness
6. **Action Items** — Specific, actionable items to prevent recurrence
7. **Lessons Learned** — Key takeaways for the team

Be thorough, objective, and actionable. Use clear headings and bullet points."""


class PostMortemWriter(AgentBase):
    """Agent responsible for generating incident documentation."""

    def __init__(self, qwen_client):
        super().__init__(
            name="postmortem_writer",
            role="documentation",
            system_prompt=SYSTEM_PROMPT
        )
        self.qwen_client = qwen_client

    async def generate_postmortem(self, incident_transcript: dict) -> dict:
        """
        Generate a comprehensive post-mortem document.

        Args:
            incident_transcript: Full incident data including all agent outputs

        Returns:
            Dictionary with post-mortem content
        """
        # Format transcript for LLM consumption
        transcript_text = self._format_transcript(incident_transcript)

        user_input = f"Generate a comprehensive incident post-mortem from the following transcript:\n\n{transcript_text}"

        response = await self.qwen_client.analyze_with_context(
            system_prompt=self.system_prompt,
            user_input=user_input
        )

        return {
            "postmortem": response.get("raw_response", ""),
            "generated_at": "incident_completed"
        }

    def _format_transcript(self, transcript: dict) -> str:
        """Format the incident transcript into a readable string for the LLM."""
        parts = []
        parts.append("=== INCIDENT TRANSCRIPT ===")
        
        for agent_name, data in transcript.items():
            parts.append(f"\n--- {agent_name} ---")
            if isinstance(data, dict):
                for key, value in data.items():
                    parts.append(f"{key}: {value}")
            else:
                parts.append(str(data))
        
        parts.append("\n=== END TRANSCRIPT ===")
        return "\n".join(parts)

    async def analyze(self, incident_data: dict) -> dict:
        """Post-Mortem Writer does not analyze raw data — it generates documentation."""
        return {"error": "PostMortemWriter uses generate_postmortem(), not analyze()"}
