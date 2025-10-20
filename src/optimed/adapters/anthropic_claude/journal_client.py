from __future__ import annotations

import os 
from typing import Sequence, cast, AsyncGenerator

import anthropic 
from anthropic.types import Message, MessageParam

from optimed.core.domain import ChatMessage, ChatRole
from optimed.core.ports import LLMClient

"""
Adapter: Anthropic Claude
Implements the LLMClient Protocol defined in core/ports.py.
"""

class AnthropicClaudeJournalClient(LLMClient):
    """
    Thin async wrapper around the Anthropic Claude API.
    - Converts our domain-level ChatMessage list to Claude format
    - Returns a new ChatMessage(role="ASSISTANT", ...)
    """

    def __init__(
            self,
            *,
            model: str = "claude-3-5-haiku-20241022",
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
            json_mode: bool = False,
            *,
            temperature: float = 0.7,
            max_tokens: int | None = None,
            enable_chunk_citations: bool = False,
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
        
        if json_mode:
            json_instruction = """Please respond with valid JSON only. Do not include any text outside of the JSON structure. 

IMPORTANT: Your response must be properly formatted JSON that can be parsed. If you cannot provide the requested information, return a valid JSON object with appropriate null/empty values rather than no response at all.

Example format:
{
    "field1": "value1",
    "field2": ["item1", "item2"],
    "field3": 0.5
}"""
            if system_prompt is not None:
                system_prompt = f"{system_prompt}\n\n{json_instruction}"
            else:
                system_prompt = json_instruction


        claude_msgs_typed = cast("list[MessageParam]", claude_msgs)

        response: Message | None = None

        if system_prompt is not None:
            response = await self._client.messages.create(
                model=self._model,
                messages=claude_msgs_typed,
                system=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens or 8192,  # Claude's default max tokens
            )
        else:
            response = await self._client.messages.create(
                model=self._model,
                messages=claude_msgs_typed,
                temperature=temperature,
                max_tokens=max_tokens or 8192,  # Claude's default max tokens
            )

        assistant_text = "".join(
            getattr(block, "text", "") for block in response.content
            if getattr(block, "type", None) == "text"
        )

        return ChatMessage(
            role=ChatRole.ASSISTANT,
            content=assistant_text,
            metadata={
                "model": self._model, 
                "response_id": response.id,
                "input_tokens": str(response.usage.input_tokens),
                "output_tokens": str(response.usage.output_tokens)
                },
        )

    async def chat_stream(  # type: ignore
            self,
            messages: Sequence[ChatMessage],
            json_mode: bool = False,
            *,
            temperature: float = 0.7,
            max_tokens: int | None = None,
            enable_chunk_citations: bool = False,
    ) -> AsyncGenerator[str, None]: 
        """
        Stream chat response from Claude.
        Yields text chunks as they are generated.
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
        
        if json_mode:
            json_instruction = """Please respond with valid JSON only. Do not include any text outside of the JSON structure. 

IMPORTANT: Your response must be properly formatted JSON that can be parsed. If you cannot provide the requested information, return a valid JSON object with appropriate null/empty values rather than no response at all.

Example format:
{
    "field1": "value1",
    "field2": ["item1", "item2"],
    "field3": 0.5
}"""
            if system_prompt is not None:
                system_prompt = f"{system_prompt}\n\n{json_instruction}"
            else:
                system_prompt = json_instruction

        claude_msgs_typed = cast("list[MessageParam]", claude_msgs)

        if system_prompt is not None:
            stream = await self._client.messages.create(
                model=self._model,
                messages=claude_msgs_typed,
                system=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens or 8192,
                stream=True
            )
        else:
            stream = await self._client.messages.create(
                model=self._model,
                messages=claude_msgs_typed,
                temperature=temperature,
                max_tokens=max_tokens or 8192,
                stream=True
            )

        async for chunk in stream:
            if chunk.type == "content_block_delta":
                if hasattr(chunk.delta, "text"):
                    yield chunk.delta.text
    