"""Base agent class for all ResQ agents."""

from abc import ABC, abstractmethod
from typing import Any
import uuid
from datetime import datetime


class AgentBase(ABC):
    """Abstract base class for all incident response agents."""

    def __init__(self, name: str, role: str, system_prompt: str):
        self.name = name
        self.role = role
        self.system_prompt = system_prompt
        self.agent_id = str(uuid.uuid4())

    @abstractmethod
    async def analyze(self, incident_data: dict) -> dict:
        """
        Analyze incident data and produce output.
        
        Args:
            incident_data: Dictionary containing incident-related data
            
        Returns:
            Dictionary with analysis results
        """
        pass

    def create_message(self, recipient: str, message_type: str, payload: dict) -> dict:
        """Create a structured inter-agent message."""
        return {
            "message_id": str(uuid.uuid4()),
            "sender": self.name,
            "recipient": recipient,
            "timestamp": datetime.utcnow().isoformat(),
            "type": message_type,
            "payload": payload
        }

    def __repr__(self):
        return f"<Agent: {self.name} ({self.role})>"
