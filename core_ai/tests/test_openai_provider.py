import asyncio
import json
import os

import pytest
import httpx
from core_ai.providers.openai import OpenAIProvider
from core_ai.types import Message, StreamEvent
from dotenv import load_dotenv

load_dotenv(override=True)


def test_gpt_5_6_uses_responses_reasoning_stream() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/responses"
        payload = json.loads(request.content)
        assert payload["reasoning"] == {"effort": "medium", "summary": "auto"}
        body = "\n\n".join(
            f"data: {event}"
            for event in (
                '{"type":"response.reasoning_summary_text.delta","summary_index":0,"delta":"Checking files"}',
                '{"type":"response.output_text.delta","content_index":0,"delta":"Done"}',
                '{"type":"response.completed","response":{"usage":{"input_tokens":10,"output_tokens":7,"output_tokens_details":{"reasoning_tokens":4},"total_tokens":17}}}',
                "[DONE]",
            )
        )
        return httpx.Response(200, text=body)

    async def collect() -> list[StreamEvent]:
        provider = OpenAIProvider(
            api_key="test",
            transport=httpx.MockTransport(handler),
        )
        return [
            event
            async for event in provider.stream(
                "gpt-5.6-luna", [Message(role="user", content="Inspect it")]
            )
        ]

    events = asyncio.run(collect())
    assert [(event.type, event.delta) for event in events[:2]] == [
        ("reasoning_delta", "Checking files"),
        ("text_delta", "Done"),
    ]
    assert events[2].reasoning_tokens == 4
    assert events[-1].type == "done"


def test_legacy_reasoning_model_uses_completion_stream() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        payload = json.loads(request.content)
        assert payload["reasoning_effort"] == "medium"
        body = "\n\n".join(
            f"data: {event}"
            for event in (
                '{"choices":[{"index":0,"delta":{"content":"Done"}}]}',
                "[DONE]",
            )
        )
        return httpx.Response(200, text=body)

    async def collect() -> list[StreamEvent]:
        provider = OpenAIProvider(
            api_key="test",
            transport=httpx.MockTransport(handler),
        )
        return [
            event
            async for event in provider.stream(
                "o3", [Message(role="user", content="Inspect it")]
            )
        ]

    events = asyncio.run(collect())
    assert events[0].delta == "Done"
    assert events[-1].type == "done"


def test_regular_model_uses_responses_stream() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/responses"
        body = "\n\n".join(
            f"data: {event}"
            for event in (
                '{"type":"response.output_text.delta","content_index":0,"delta":"Done"}',
                "[DONE]",
            )
        )
        return httpx.Response(200, text=body)

    async def collect() -> list[StreamEvent]:
        provider = OpenAIProvider(api_key="test", transport=httpx.MockTransport(handler))
        return [
            event
            async for event in provider.stream(
                "gpt-4o-mini", [Message(role="user", content="Do it")]
            )
        ]

    events = asyncio.run(collect())
    assert events[0].delta == "Done"
    assert events[-1].type == "done"


def call_openai_provider(
    prompt: str = "what is 3+5. just answer in number",
    model_name: str | None = None,
) -> str:
    if os.getenv("RUN_LIVE_OPENAI_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_OPENAI_TESTS=1 to run the OpenAI provider smoke test.")
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
