from __future__ import annotations

import os
from typing import Sequence, AsyncGenerator, List, Dict, Any

import openai

from optimed.core.domain import ChatMessage, ChatRole
from optimed.core.ports import LLMClient


class AzureOpenAIGPT5MiniClient(LLMClient):
    """
    Async wrapper around Azure OpenAI (GPT-5 mini deployment) for fast responses.

    Notes:
    - Mirrors the interface/behavior of OpenAIGPT5MiniClient but targets Azure.
    - Uses Azure-specific environment variables and endpoint configuration.
    - The `model` parameter refers to the Azure deployment name.
    - Encourages minimal reasoning effort via a lightweight system directive.
    - Implements the LLMClient protocol used across the app.
    """

    def __init__(
        self,
        *,
        model: str = "gpt-5-mini",
        api_key: str | None = None,
        timeout: float | None = None,
        minimal_reasoning: bool = True,
        azure_endpoint: str | None = None,
        api_version: str | None = None,
    ) -> None:
        # Use Azure-specific async client to ensure proper auth headers (api-key) and API versioning
        self._client = openai.AsyncOpenAI(  # type: ignore[attr-defined]
            api_key=api_key or os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("AZURE_OPENAI_KEY"),
            base_url=azure_endpoint or os.getenv("AZURE_OPENAI_ENDPOINT"),
            timeout=timeout,
        )
        
        self._model = model
        self._minimal_reasoning = minimal_reasoning

    @staticmethod
    def _to_responses_input(messages: Sequence[ChatMessage]) -> List[Dict[str, Any]]:
        """
        Map your app's ChatMessage list to the Responses API 'input' format.
        We use explicit content parts for forward-compat with multimodal.
        """
        inputs: List[Dict[str, Any]] = []
        for msg in messages:
            inputs.append({
                "role": msg.role.value,
                "content": [
                    {"type": "input_text", "text": msg.content}
                ],
            })
        return inputs

    async def chat(  # type: ignore
        self,
        messages: Sequence[ChatMessage],
        json_mode: bool = False,
        max_tokens: int | None = None,
    ) -> ChatMessage:
        # Build input payload
        input_payload = self._to_responses_input(messages)


        # If you prefer an extra safety belt, you can still append a JSON instruction:
        if json_mode and input_payload and input_payload[-1]["role"] == "user":
            input_payload[-1]["content"].append({
                "type": "input_text",
                "text": "Please return ONLY strict, valid JSON with no extra text."
            })

        # Build request kwargs
        kwargs: Dict[str, Any] = {
            "model": self._model,
            "input": input_payload,
        }
        if max_tokens is not None:
            kwargs["max_output_tokens"] = max_tokens
        else:
            kwargs["max_output_tokens"] = 32000

        # Reasoning effort in Responses API
        if self._minimal_reasoning:
            kwargs["reasoning"] = {"effort": "minimal"}

        # Call Responses API
        response = await self._client.responses.create(**kwargs)

        assistant_text = getattr(response, "output_text", "") or ""

        usage = getattr(response, "usage", None)
        input_tokens = str(getattr(usage, "input_tokens", 0)) if usage else "0"
        output_tokens = str(getattr(usage, "output_tokens", 0)) if usage else "0"
        total_tokens = str(getattr(usage, "total_tokens", 0)) if usage else "0"

        return ChatMessage(
            role=ChatRole.ASSISTANT,
            content=assistant_text,
            metadata={
                "model": self._model,
                "response_id": response.id,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "reasoning_effort": "minimal" if self._minimal_reasoning else "default",
            },
        )

    async def chat_stream(  # type: ignore
        self,
        messages: Sequence[ChatMessage],
        json_mode: bool = False,
        max_tokens: int | None = None,
    ) -> AsyncGenerator[str, None]:
        # Build input payload
        input_payload = self._to_responses_input(messages)

        if json_mode and input_payload and input_payload[-1]["role"] == "user":
            input_payload[-1]["content"].append({
                "type": "input_text",
                "text": "Please return ONLY strict, valid JSON with no extra text."
            })

        kwargs: Dict[str, Any] = {
            "model": self._model,
            "input": input_payload,
            "stream": True,
        }
        if max_tokens is not None:
            kwargs["max_output_tokens"] = max_tokens
        else:
            kwargs["max_output_tokens"] = 32000

        if self._minimal_reasoning:
            kwargs["reasoning"] = {"effort": "minimal"}

        stream = await self._client.responses.create(**kwargs)

        # The stream yields typed events; we only forward text deltas.
        async for event in stream:
            # Text delta events:
            if getattr(event, "type", "") == "response.output_text.delta":
                delta = getattr(event, "delta", None)
                if delta:
                    yield delta

