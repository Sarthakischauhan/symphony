import asyncio
import json

import httpx

from core_ai.models import ModelInfo, register_model, unregister_model
from core_ai.providers.grok import GrokProvider
from core_ai.types import Message, StreamEvent


def test_grok_uses_chat_completions_stream() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        payload = json.loads(request.content)
        assert payload["model"] == "grok-4.6"
        assert payload["reasoning_effort"] == "high"
        assert payload["max_completion_tokens"] == 900
        body = "\n\n".join(
            f"data: {event}"
            for event in (
                '{"choices":[{"index":0,"delta":{"content":"Done"}}]}',
                "[DONE]",
            )
        )
        return httpx.Response(200, text=body)

    async def collect() -> list[StreamEvent]:
        provider = GrokProvider(api_key="test", transport=httpx.MockTransport(handler))
        return [
            event
            async for event in provider.stream(
                "grok-4.6",
                [Message(role="user", content="Inspect it")],
                max_output_tokens=900,
                reasoning_effort="high",
            )
        ]

    events = asyncio.run(collect())
    assert events[0].delta == "Done"
    assert events[-1].type == "done"


def test_grok_skips_reasoning_effort_for_non_reasoning_models() -> None:
    register_model(
        ModelInfo(id="grok-fast", provider="grok", api="chat_completions", reasoning=False)
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert "reasoning_effort" not in payload
        body = "\n\n".join(
            (
                'data: {"choices":[{"index":0,"delta":{"content":"Hi"}}]}',
                "data: [DONE]",
            )
        )
        return httpx.Response(200, text=body)

    async def collect() -> list[StreamEvent]:
        provider = GrokProvider(api_key="test", transport=httpx.MockTransport(handler))
        try:
            return [
                event
                async for event in provider.stream(
                    "grok-fast",
                    [Message(role="user", content="Hi")],
                    reasoning_effort="high",
                )
            ]
        finally:
            unregister_model("grok", "grok-fast")

    events = asyncio.run(collect())
    assert events[0].delta == "Hi"
    assert events[-1].type == "done"


def test_grok_unknown_models_use_chat_completions() -> None:
    assert GrokProvider._uses_chat_completions("grok-future") is True
    assert GrokProvider._is_reasoning_model("grok-future") is True
