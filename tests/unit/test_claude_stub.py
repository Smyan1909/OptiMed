import pytest
from optimed.core.domain import ChatMessage, ChatRole
from optimed.adapters.anthropic_claude.client import AnthropicClaudeClient

@pytest.mark.asyncio
async def test_claude_stub(monkeypatch):
    async def _fake_create(*args, **kwargs):
        class _Resp:
            id = "fake123"
            usage = type("U", (), {"input_tokens": 5, "output_tokens": 7})
            content = [type("B", (), {"text": "Hello from stub"})]
        return _Resp()
    # Monkey-patch SDK
    monkeypatch.setattr(
        "adapters.anthropic_claude.client.AnthropicClaudeClient._client.messages.create",
        _fake_create,
    )
    client = AnthropicClaudeClient(api_key="dummy")
    reply = await client.chat([ChatMessage(role=ChatRole.USER, content="hi")])
    assert reply.role is ChatRole.ASSISTANT
    assert "Hello" in reply.content