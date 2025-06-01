from __future__ import annotations

import os 
from typing import Sequence

import anthropic 
from anthropic.types import Message, ContentBlock

from optimed.core.domain import ChatMessage, ChatRole
from optimed.core.ports import LLMClient


"""
Adapter: Anthropic Claude
Implements the LLMClient Protocol defined in core/ports.py.
"""

class AnthropicClaudeClient(LLMClient):
    """
    Thin async wrapper around the Anthropic Claude API.
    - Converts our domain-level ChatMessage list to Claude format
    - Returns a new ChatMessage(role="ASSISTANT", ...)
    """

    def __init__(
            self,
            *,
            model: str = "claude-3-5-sonnet-20241022",
            api_key: str | None = None,
            timeout: float | None = None,
    ) -> None:
        
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key or os.getenv("ANTHROPIC_API_KEY"),
            timeout=timeout,
        )
        self._model = model

    async def chat(
            self,
            messages: Sequence[ChatMessage],
            *,
            temperature: float = 0.7,
            max_tokens: int | None = None,
    ) -> ChatMessage:
        """
        • Pull out the *first* system prompt (optional)
        • Map USER / ASSISTANT turns → Claude’s schema
        • Fire the request asynchronously
        • Wrap the assistant answer back into our ChatMessage VO
        """
        system_prompt: str | None = None
        claude_msgs: list[dict[str, str]] = []

        for msg in messages:
            if msg.role is ChatRole.SYSTEM and system_prompt is None:
                system_prompt = msg.content
            else:
                claude_msgs.append({
                    "role": msg.role.value,
                    "content": msg.content
                })
        
        response: Message = await self._client.messages.create(
            model=self._model,
            system=system_prompt,
            messages=claude_msgs,
            temperature=temperature,
            max_tokens=max_tokens or 4096,  # Claude's default max tokens
        )

        assistant_text = "".join(
            block.text for block in response.content if isinstance(block, ContentBlock)
        )

        return ChatMessage(
            role=ChatRole.ASSISTANT,
            content=assistant_text,
            timestamp=response.created_at,
            metadata={
                "model": self._model, 
                "response_id": response.id,
                "input_tokens": str(response.usage.input_tokens),
                "output_tokens": str(response.usage.output_tokens)
                },
        )
    