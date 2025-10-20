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

    Context Window:
    - Total: 400,000 tokens
    - Input: Up to 272,000 tokens
    - Output: Up to 128,000 tokens
    - Default output: 8,192 tokens (configurable via GPT5_DEFAULT_MAX_TOKENS)

    Important: Setting high max_output_tokens reduces available input capacity.
    Formula: Available_Input = 400k - max_output_tokens
    """

    def __init__(
        self,
        *,
        model: str = "gpt-5-mini-europe",  # Azure deployment name
        api_key: str | None = None,
        timeout: float | None = None,
        minimal_reasoning: bool = True,
        azure_endpoint: str | None = None,
        api_version: str | None = None,
        default_max_tokens: int | None = None,  # Auto-detect from env or use 8192
    ) -> None:
        # Use Azure-specific async client to ensure proper auth headers (api-key) and API versioning
        self._client = openai.AsyncOpenAI(  # type: ignore[attr-defined]
            api_key=api_key or os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("AZURE_OPENAI_KEY"),
            base_url=azure_endpoint or os.getenv("AZURE_OPENAI_ENDPOINT"),
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
        enable_chunk_citations: bool = False,
    ) -> ChatMessage:
        # Build input payload
        input_payload = self._to_responses_input(messages)

        # Chunk citations require JSON mode
        if enable_chunk_citations:
            json_mode = True

        # If you prefer an extra safety belt, you can still append a JSON instruction:
        if json_mode and input_payload and input_payload[-1]["role"] == "user":
            if enable_chunk_citations:
                # Special JSON instruction for numbered citations
                json_instruction = """RESPONSE FORMAT (REQUIRED):
You must respond with valid JSON in this exact structure:
{
  "response": "Your clinical response here. When using information from a source, include [X] immediately after the statement, where X is the citation number.",
  "cited_chunks": ["1", "2", "3"]
}

CITATION RULES:
1. The clinical information is labeled with "[Citation: 1]", "[Citation: 2]", etc.
2. Cite the source IMMEDIATELY after the sentence that uses its information
3. Use the EXACT number shown in the "[Citation: X]" markers - just put [X] after your statement
4. Example: If you see "[Citation: 3]\\nPatient is 87 years old", write "Patient is 87 years old [3]"
5. In cited_chunks, list the citation numbers you actually used (as strings)

IMPORTANT: Response must be valid JSON only. No text outside the JSON structure."""
            else:
                json_instruction = "Please return ONLY strict, valid JSON with no extra text."

            input_payload[-1]["content"].append({
                "type": "input_text",
                "text": json_instruction
            })

        # Build request kwargs
        kwargs: Dict[str, Any] = {
            "model": self._model,
            "input": input_payload,
        }
        # Use provided max_tokens, or default to GPT-5 mini's max (128k)
        kwargs["max_output_tokens"] = max_tokens if max_tokens is not None else self._default_max_tokens

        # Reasoning effort in Responses API
        if self._minimal_reasoning:
            kwargs["reasoning"] = {"effort": "minimal"}

        # Call Responses API
        response = await self._client.responses.create(**kwargs)

        assistant_text = getattr(response, "output_text", "") or ""

        # Parse cited chunks if chunk citations are enabled
        cited_chunk_ids = None
        if enable_chunk_citations and assistant_text:
            try:
                import json
                response_json = json.loads(assistant_text)
                cited_chunk_ids = response_json.get("cited_chunks", [])
                # Extract the actual response content
                assistant_text = response_json.get("response", assistant_text)
            except json.JSONDecodeError:
                # If parsing fails, return the raw text
                pass

        usage = getattr(response, "usage", None)
        input_tokens = str(getattr(usage, "input_tokens", 0)) if usage else "0"
        output_tokens = str(getattr(usage, "output_tokens", 0)) if usage else "0"
        total_tokens = str(getattr(usage, "total_tokens", 0)) if usage else "0"

        return ChatMessage(
            role=ChatRole.ASSISTANT,
            content=assistant_text,
            cited_chunk_ids=cited_chunk_ids,
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
        enable_chunk_citations: bool = False,
    ) -> AsyncGenerator[str, None]:
        # Build input payload
        input_payload = self._to_responses_input(messages)

        # Chunk citations require JSON mode
        if enable_chunk_citations:
            json_mode = True

        if json_mode and input_payload and input_payload[-1]["role"] == "user":
            if enable_chunk_citations:
                # Special JSON instruction for numbered citations
                json_instruction = """RESPONSE FORMAT (REQUIRED):
You must respond with valid JSON in this exact structure:
{
  "response": "Your clinical response here. When using information from a source, include [X] immediately after the statement, where X is the citation number.",
  "cited_chunks": ["1", "2", "3"]
}

CITATION RULES:
1. The clinical information is labeled with "[Citation: 1]", "[Citation: 2]", etc.
2. Cite the source IMMEDIATELY after the sentence that uses its information
3. Use the EXACT number shown in the "[Citation: X]" markers - just put [X] after your statement
4. Example: If you see "[Citation: 3]\\nPatient is 87 years old", write "Patient is 87 years old [3]"
5. In cited_chunks, list the citation numbers you actually used (as strings)

IMPORTANT: Response must be valid JSON only. No text outside the JSON structure."""
            else:
                json_instruction = "Please return ONLY strict, valid JSON with no extra text."

            input_payload[-1]["content"].append({
                "type": "input_text",
                "text": json_instruction
            })

        kwargs: Dict[str, Any] = {
            "model": self._model,
            "input": input_payload,
            "stream": True,
        }
        # Use provided max_tokens, or default to GPT-5 mini's max (128k)
        kwargs["max_output_tokens"] = max_tokens if max_tokens is not None else self._default_max_tokens

        if self._minimal_reasoning:
            kwargs["reasoning"] = {"effort": "minimal"}

        try:
            stream = await self._client.responses.create(**kwargs)

            # The stream yields typed events; we only forward text deltas.
            async for event in stream:
                # Text delta events:
                if getattr(event, "type", "") == "response.output_text.delta":
                    delta = getattr(event, "delta", None)
                    if delta:
                        yield delta
        except Exception as e:
            # Handle network errors gracefully
            import logging
            logging.error(f"Azure GPT streaming error: {e}")
            # Re-raise with more context
            raise Exception(f"Failed to stream from Azure GPT: {e}") from e

