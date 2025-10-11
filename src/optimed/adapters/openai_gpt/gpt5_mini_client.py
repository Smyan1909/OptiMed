from __future__ import annotations

import os
from typing import Sequence, AsyncGenerator

import openai

from optimed.core.domain import ChatMessage, ChatRole
from optimed.core.ports import LLMClient


class OpenAIGPT5MiniClient(LLMClient):
    """
    Async wrapper around OpenAI GPT-5 mini for fast responses.

    Notes:
    - Defaults to model "gpt-5-mini" for speed.
    - Encourages minimal reasoning effort via a lightweight system directive.
    - Implements the LLMClient protocol used across the app.

    Context Window:
    - Total: 400,000 tokens
    - Input: Up to 272,000 tokens
    - Output: Up to 128,000 tokens
    - Default output: 8,192 tokens (configurable via GPT5_DEFAULT_MAX_TOKENS)

    Important: Setting high max_completion_tokens reduces available input capacity.
    Formula: Available_Input = 400k - max_completion_tokens
    """

    def __init__(
        self,
        *,
        model: str = "gpt-5-mini",
        api_key: str | None = None,
        timeout: float | None = None,
        minimal_reasoning: bool = True,
        default_max_tokens: int | None = None,  # Auto-detect from env or use 8192
    ) -> None:
        self._client = openai.AsyncOpenAI(
            api_key=api_key or os.getenv("OPENAI_API_KEY"),
            timeout=timeout,
        )
        self._model = model
        self._minimal_reasoning = minimal_reasoning

        # Allow configuration via environment variable
        if default_max_tokens is None:
            env_max = os.getenv("GPT5_DEFAULT_MAX_TOKENS")
            self._default_max_tokens = int(env_max) if env_max else 8192
        else:
            self._default_max_tokens = default_max_tokens

    async def chat(  # type: ignore
        self,
        messages: Sequence[ChatMessage],
        json_mode: bool = False,
        max_tokens: int | None = None,
    ) -> ChatMessage:
        openai_msgs: list[dict[str, str]] = [
            {"role": msg.role.value, "content": msg.content} for msg in messages
        ]

        # Configure response format for JSON mode
        response_format = {"type": "json_object"} if json_mode else {"type": "text"}

        if json_mode:
            json_instruction = (
                "Please respond with valid JSON only. Do not include any text outside of the JSON structure."
            )
            if openai_msgs and openai_msgs[-1]["role"] == "user":
                openai_msgs[-1]["content"] = f"{openai_msgs[-1]['content']}\n\n{json_instruction}"
            else:
                openai_msgs.append({"role": "system", "content": json_instruction})

        # Use Chat Completions for compatibility with existing flow
        response = await self._client.chat.completions.create(  # type: ignore
            model=self._model,
            messages=openai_msgs,
            max_completion_tokens=max_tokens or self._default_max_tokens,  # Up to 128k for GPT-5 mini
            response_format=response_format,
            reasoning_effort="minimal" if self._minimal_reasoning else "default",
        )

        assistant_text = response.choices[0].message.content or ""

        return ChatMessage(
            role=ChatRole.ASSISTANT,
            content=assistant_text,
            metadata={
                "model": self._model,
                "response_id": response.id,
                "input_tokens": str(response.usage.prompt_tokens) if response.usage else "0",
                "output_tokens": str(response.usage.completion_tokens) if response.usage else "0",
                "total_tokens": str(response.usage.total_tokens) if response.usage else "0",
                "reasoning_effort": "minimal" if self._minimal_reasoning else "default",
            },
        )

    async def chat_stream(  # type: ignore
        self,
        messages: Sequence[ChatMessage],
        json_mode: bool = False,
        max_tokens: int | None = None,
    ) -> AsyncGenerator[str, None]:
        openai_msgs: list[dict[str, str]] = [
            {"role": msg.role.value, "content": msg.content} for msg in messages
        ]

        response_format = {"type": "json_object"} if json_mode else {"type": "text"}

        if json_mode:
            json_instruction = (
                "Please respond with valid JSON only. Do not include any text outside of the JSON structure."
            )
            if openai_msgs and openai_msgs[-1]["role"] == "user":
                openai_msgs[-1]["content"] = f"{openai_msgs[-1]['content']}\n\n{json_instruction}"
            else:
                openai_msgs.append({"role": "system", "content": json_instruction})

        stream = await self._client.chat.completions.create(  # type: ignore
            model=self._model,
            messages=openai_msgs,
            max_completion_tokens=max_tokens or self._default_max_tokens,  # Up to 128k for GPT-5 mini
            response_format=response_format,
            reasoning_effort="minimal" if self._minimal_reasoning else "default",
            stream=True,
        )

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


