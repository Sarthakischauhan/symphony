import asyncio
import os

import pytest
from core_ai.providers.openai import OpenAIProvider
from core_ai.types import Message
from dotenv import load_dotenv

load_dotenv(override=True)


def call_openai_provider(
    prompt: str = "what is 3+5. just answer in number",
    model_name: str | None = None,
) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("Set OPENAI_API_KEY to run the OpenAI provider smoke test.")

    provider = OpenAIProvider(
        api_key=api_key,
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    )
    selected_model = model_name or os.getenv("OPENAI_TEST_MODEL", "gpt-4o-mini")
    messages = [Message(role="user", content=prompt)]

    return asyncio.run(_collect_text(provider, selected_model, messages))


async def _collect_text(
    provider: OpenAIProvider, model_name: str, messages: list[Message]
) -> str:
    chunks: list[str] = []

    async for event in provider.stream(model_name=model_name, messages=messages):
        if event.type == "text_delta" and event.delta:
            chunks.append(event.delta)

    return "".join(chunks).strip()


def test_openai_provider_smoke() -> None:
    response_text = call_openai_provider()
    assert response_text == "8"
