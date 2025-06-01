import pytest
from optimed.core.domain import ChatMessage, ChatRole
from optimed.adapters.anthropic_claude.client import AnthropicClaudeClient

@pytest.mark.asyncio
async def test_claude_stub(monkeypatch):
    async def _fake_create(*args, **kwargs):
        # minimal stub that looks like Anthropic's Message
        class _Resp:
            id = "fake123"
            usage = type("U", (), {"input_tokens": 5, "output_tokens": 7})
            content = [type("B", (), {"type": "text", "text": "Hello from stub"})]

        return _Resp()

    llm = AnthropicClaudeClient(api_key="dummy")

    # 👉 patch the *instance’s* messages.create method
    monkeypatch.setattr(
        llm._client.messages,          # real object we just constructed
        "create",
        _fake_create,
        raising=True,
    )

    reply = await llm.chat([ChatMessage(role=ChatRole.USER, content="hi")])

    assert reply.role is ChatRole.ASSISTANT
    assert reply.content == "Hello from stub"