"""Qwen Cloud API client for agent reasoning.

This module provides the integration with Qwen Cloud APIs for all agent reasoning.
Required for hackathon submission - demonstrates Qwen Cloud API usage.
"""

import os
import asyncio
from typing import Optional, List, Dict
import logging

logger = logging.getLogger(__name__)

try:
    from openai import AsyncOpenAI
except ImportError:
    AsyncOpenAI = None


class QwenClient:
    """Async client for Qwen Cloud API interactions."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        model: str = "qwen-plus"
    ):
        if AsyncOpenAI is None:
            raise ImportError(
                "openai package required. Install with: pip install openai"
            )
        
        self.api_key = api_key or os.getenv("QWEN_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Qwen API key required. Set QWEN_API_KEY environment variable."
            )
        
        self.base_url = base_url
        self.model = model
        self._client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )

    async def chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000
    ) -> str:
        """
        Send a chat completion request to Qwen Cloud.

        Args:
            messages: List of message dicts with 'role' and 'content'
            system_prompt: Optional system prompt to prepend
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Maximum tokens to generate

        Returns:
            Generated text response
        """
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=full_messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Qwen API error: {e}")
            raise

    async def analyze_with_context(
        self,
        system_prompt: str,
        user_input: str,
        response_format: Optional[dict] = None
    ) -> dict:
        """
        Analyze data with structured output expectation.

        Args:
            system_prompt: Agent-specific system prompt
            user_input: Data to analyze
            response_format: Optional JSON schema for structured output

        Returns:
            Parsed response (dict)
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input}
        ]

        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.3,  # Lower for analysis tasks
            "max_tokens": 3000
        }
        
        if response_format:
            kwargs["response_format"] = response_format

        try:
            response = await self._client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content
            # In production, parse JSON here. For now, return raw content
            return {"raw_response": content}
        except Exception as e:
            logger.error(f"Qwen analysis error: {e}")
            return {"error": str(e), "raw_response": ""}
