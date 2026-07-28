import asyncio
import os

import pytest
from core_ai.providers.openai import OpenAIProvider
from core_ai.types import Message, StreamEvent
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

    return asyncio.run(_collect_text_and_usage(provider, selected_model, messages))


async def _collect_text_and_usage(
    provider: OpenAIProvider, model_name: str, messages: list[Message]
) -> str:
    chunks: list[str] = []
    usage = []
    async for event in provider.stream(model_name=model_name, messages=messages):
        if event.type == "text_delta" and event.delta:
            chunks.append(event.delta)
        if event.type == "usage":
            usage.append({
                "prompt_tokens": event.prompt_tokens,
                "total_tokens": event.total_tokens,
            })

    return ("".join(chunks).strip(), usage)


def test_openai_provider_smoke() -> None:
    response_text, _= call_openai_provider()
    assert response_text == "8"

def test_openai_provider_with_usage() -> None:
    response_text, usage = call_openai_provider("how many letters in word pizza ? just answer in number")
    assert response_text  == "5"

    assert usage is not None
