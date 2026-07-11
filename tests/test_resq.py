"""Tests for ResQ agents and consensus mechanism."""

import pytest
import asyncio
from core.consensus import ConsensusEngine
from core.communication import MessageBus


# ==================== Consensus Engine Tests ====================

class TestConsensusEngine:
    """Test the conflict resolution mechanism."""

    def setup_method(self):
        self.engine = ConsensusEngine()

    def test_single_hypothesis_wins(self):
        """When only one agent provides a hypothesis, it should win."""
        hyp_a = [{
            "cause": "Memory leak in service-x",
            "confidence": 0.80,
            "evidence": ["RSS growth 2GB in 30min"],
            "severity": "high"
        }]
        hyp_b = []

        winner, justification = self.engine.resolve(hyp_a, hyp_b)
        assert winner["cause"] == "Memory leak in service-x"
        assert winner["adjusted_score"] >= 0.80

    def test_cross_agent_confirmation_bonus(self):
        """When both agents agree, confidence should increase."""
        hyp_a = [{
            "cause": "Database connection pool exhausted",
            "confidence": 0.75,
            "evidence": ["pool at max"],
            "severity": "high"
        }]
        hyp_b = [{
            "cause": "Database connection pool exhausted",
            "confidence": 0.70,
            "evidence": ["connection timeout spike"],
            "severity": "high"
        }]

        winner, justification = self.engine.resolve(hyp_a, hyp_b)
        # Both agree, so cross-agent bonus should apply
        assert winner.get("cross_agent_confirmed") is True
        assert winner["adjusted_score"] > 0.75

    def test_conflicting_hypotheses(self):
        """When agents disagree, higher-confidence hypothesis should win."""
        hyp_a = [{
            "cause": "Memory leak",
            "confidence": 0.85,
            "evidence": ["heap growth"],
            "severity": "high"
        }]
        hyp_b = [{
            "cause": "CPU throttling",
            "confidence": 0.60,
            "evidence": ["CPU spike"],
            "severity": "medium"
        }]

        winner, _ = self.engine.resolve(hyp_a, hyp_b)
        assert winner["cause"] == "Memory leak"

    def test_no_hypotheses_fallback(self):
        """When no hypotheses provided, should return fallback."""
        winner, justification = self.engine.resolve([], [])
        assert "Unknown" in winner["cause"]
        assert winner["confidence"] == 0.0

    def test_evidence_bonus(self):
        """More evidence should increase score (capped)."""
        hyp_a = [{
            "cause": "Network issue",
            "confidence": 0.50,
            "evidence": ["e1", "e2", "e3", "e4", "e5", "e6"],
            "severity": "medium"
        }]
        hyp_b = []

        winner, _ = self.engine.resolve(hyp_a, hyp_b)
        # Evidence bonus capped at 0.1
        assert winner["adjusted_score"] == 0.50 + 0.10  # 0.60


# ==================== Communication Tests ====================

class TestMessageBus:
    """Test the inter-agent message bus."""

    @pytest.mark.asyncio
    async def test_send_receive(self):
        """Messages should be sent and received correctly."""
        bus = MessageBus()
        bus.register_agent("sender")
        bus.register_agent("receiver")

        message = {
            "message_id": "test-001",
            "sender": "sender",
            "recipient": "receiver",
            "type": "test_message",
            "payload": {"data": "test"}
        }

        await bus.send(message)
        received = await bus.receive("receiver", timeout=1.0)
        
        assert received is not None
        assert received["message_id"] == "test-001"
        assert received["type"] == "test_message"

    @pytest.mark.asyncio
    async def test_timeout(self):
        """Receive should timeout when no messages available."""
        bus = MessageBus()
        bus.register_agent("lonely_agent")

        result = await bus.receive("lonely_agent", timeout=0.1)
        assert result is None

    def test_message_log(self):
        """Message log should track all messages."""
        bus = MessageBus()
        assert len(bus.get_message_log()) == 0

    def test_unregistered_agent(self):
        """Sending to unregistered agent should raise."""
        bus = MessageBus()
        with pytest.raises(ValueError):
            asyncio.get_event_loop().run_until_complete(
                bus.send({"recipient": "nonexistent"})
            )


# ==================== Integration Placeholder ====================

class TestAgentIntegration:
    """Integration tests for agents with Qwen Cloud (requires API key)."""

    @pytest.mark.skip(reason="Requires QWEN_API_KEY environment variable")
    def test_log_analyzer_with_real_api(self):
        """Test Log Analyzer against real Qwen Cloud API."""
        pass

    @pytest.mark.skip(reason="Requires QWEN_API_KEY environment variable")
    def test_full_swarm_workflow(self):
        """Test full ResQ swarm workflow end-to-end."""
        pass
