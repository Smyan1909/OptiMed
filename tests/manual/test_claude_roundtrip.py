import asyncio 
from pathlib import Path
from dotenv import load_dotenv

from optimed.adapters.anthropic_claude.client import AnthropicClaudeClient
from optimed.core.domain import ChatMessage, ChatRole

async def main() -> None:
    env_file = Path(__file__).resolve().parents[2] / ".env"

    assert env_file.exists(), f"Missing .env file at {env_file}"

    load_dotenv(env_file)

    llm = AnthropicClaudeClient()

    user_msg = ChatMessage(role=ChatRole.USER, content="Hello, Claude. Tell me an interesting fact!")
    reply = await llm.chat([user_msg])

    print("--- Claude response ---")
    print(reply.content)
    print("--- Metadata ---")
    for k, v in reply.metadata.items():
        print(f"{k}: {v}")
    print("---Respons Timestamp---")
    print(reply.timestamp.isoformat())

if __name__ == "__main__":
    asyncio.run(main())