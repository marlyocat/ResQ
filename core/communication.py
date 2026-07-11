"""Inter-agent communication protocol and message bus."""

import asyncio
from typing import Dict, List, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class MessageBus:
    """Async message bus for inter-agent communication."""

    def __init__(self):
        self._queues: Dict[str, asyncio.Queue] = {}
        self._message_log: List[dict] = []

    def register_agent(self, agent_name: str):
        """Register an agent with the message bus."""
        if agent_name not in self._queues:
            self._queues[agent_name] = asyncio.Queue()
            logger.info(f"Registered agent: {agent_name}")

    async def send(self, message: dict):
        """Send a message to a specific agent."""
        recipient = message.get("recipient")
        if recipient not in self._queues:
            raise ValueError(f"Agent '{recipient}' not registered")
        
        self._message_log.append(message)
        await self._queues[recipient].put(message)
        logger.debug(f"Message sent from {message['sender']} to {recipient}: {message['type']}")

    async def receive(self, agent_name: str, timeout: float = 30.0) -> dict:
        """Receive a message for a specific agent with timeout."""
        if agent_name not in self._queues:
            raise ValueError(f"Agent '{agent_name}' not registered")
        
        try:
            message = await asyncio.wait_for(
                self._queues[agent_name].get(),
                timeout=timeout
            )
            logger.debug(f"Message received by {agent_name}: {message['type']}")
            return message
        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for message for {agent_name}")
            return None

    def get_message_log(self) -> List[dict]:
        """Get the full message log for audit/post-mortem purposes."""
        return self._message_log.copy()

    def get_conversation_for_agent(self, agent_name: str) -> List[dict]:
        """Get all messages sent to or from a specific agent."""
        return [
            msg for msg in self._message_log
            if msg["sender"] == agent_name or msg["recipient"] == agent_name
        ]
