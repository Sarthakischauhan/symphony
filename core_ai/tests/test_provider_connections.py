"""Providers keep one HTTP client, so back-to-back requests reuse a connection."""

import asyncio
import json
from typing import AsyncIterator, List, Tuple

import httpx
import pytest

from core_ai.models import ModelInfo, ModelPrice, register_model, unregister_model
from core_ai.models.pricing import turn_cost
from core_ai.providers.anthropic import AnthropicProvider
from core_ai.providers.base import BaseProvider
from core_ai.providers.gemini import GeminiProvider
from core_ai.providers.grok import GrokProvider
from core_ai.providers.http import iter_sse_json
from core_ai.providers.ollama import OllamaProvider
from core_ai.providers.openai import OpenAIProvider
from core_ai.registry import ModelRegistry
from core_ai.types import Message, StreamEvent
from sse_server import SSEServer

MESSAGES = [Message(role="system", content="Be brief"), Message(role="user", content="Hi")]
TOOLS = [{"name": "read_file", "description": "Read a file", "parameters": {"type": "object"}}]


def _sse(*frames: str) -> bytes:
    return "".join(f"data: {frame}\n\n" for frame in frames).encode()


def _frames(body: bytes) -> List[bytes]:
    return [frame + b"\n\n" for frame in body.split(b"\n\n")[:-1]]


# OpenAI-compatible chat streams end with ``[DONE]``; this one also sends a
# frame after it, which must be read but not yielded.
CHAT_BODY = _sse(
    '{"choices":[{"index":0,"delta":{"content":"Hello"}}]}',
    '{"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":2,"total_tokens":12}}',
    "[DONE]",
    '{"choices":[{"index":0,"delta":{"content":"after done"}}]}',
)
ANTHROPIC_BODY = _sse(
    '{"type":"message_start","message":{"usage":{"input_tokens":3}}}',
    '{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}',
    '{"type":"message_delta","usage":{"output_tokens":2}}',
    '{"type":"message_stop"}',
)
GEMINI_BODY = _sse(
    '{"candidates":[{"content":{"parts":[{"text":"Hello"}]}}],'
    '"usageMetadata":{"promptTokenCount":10,"candidatesTokenCount":2,"totalTokenCount":12}}',
)
FRAMES = {
    "/v1/chat/completions": _frames(CHAT_BODY),
    "/v1/messages": _frames(ANTHROPIC_BODY),
    "/v1beta/models/gemini-test:streamGenerateContent": _frames(GEMINI_BODY),
}


async def _drain(stream: AsyncIterator[StreamEvent]) -> List[StreamEvent]:
    return [event async for event in stream]


def _provider(kind: str, base: str) -> Tuple[BaseProvider, str]:
    if kind == "openai":
        return OpenAIProvider(api_key="test", base_url=f"{base}/v1"), "o4-mini"
    if kind == "anthropic":
        return AnthropicProvider(api_key="test", base_url=base), "claude-test"
    return GeminiProvider(api_key="test", base_url=f"{base}/v1beta"), "gemini-test"


@pytest.mark.parametrize("kind", ["openai", "anthropic", "gemini"])
def test_back_to_back_streams_open_no_new_connections(kind: str) -> None:
    async def run() -> Tuple[int, int, List[List[StreamEvent]]]:
        async with SSEServer(FRAMES) as server:
            provider, model = _provider(kind, server.base)
            results = [await _drain(provider.stream(model, MESSAGES, TOOLS)) for _ in range(5)]
            opened = server.connections
            await provider.aclose()
            await asyncio.sleep(0.05)
            return opened, server.closed, results

    opened, closed, results = asyncio.run(run())
    assert opened == 1
    assert closed == 1
    for events in results:
        assert [event.delta for event in events if event.type == "text_delta"] == ["Hello"]
        assert events[-1].type == "done"


def test_registry_aclose_closes_every_provider() -> None:
    async def run() -> int:
        async with SSEServer(FRAMES) as server:
            registry = ModelRegistry()
            registry.register("openai", OpenAIProvider(api_key="test", base_url=f"{server.base}/v1"))
            registry.register("anthropic", AnthropicProvider(api_key="test", base_url=server.base))
            await _drain(registry.stream("openai:o4-mini", MESSAGES, TOOLS))
            await _drain(registry.stream("anthropic:claude-test", MESSAGES, TOOLS))
            await registry.aclose()
            await asyncio.sleep(0.05)
            return server.closed

    assert asyncio.run(run()) == 2


def test_sse_reads_to_the_end_after_done() -> None:
    async def run() -> Tuple[List[dict], bool]:
        transport = httpx.MockTransport(lambda request: httpx.Response(200, content=CHAT_BODY))
        async with httpx.AsyncClient(transport=transport) as client:
            async with client.stream("POST", "http://test/v1/chat/completions") as response:
                frames = [frame async for frame in iter_sse_json(response)]
                return frames, response.is_stream_consumed

    frames, consumed = asyncio.run(run())
    assert consumed
    assert len(frames) == 2
    assert "after done" not in json.dumps(frames)


def _usage(provider: BaseProvider, model: str) -> List[StreamEvent]:
    events = asyncio.run(_drain(provider.stream(model, MESSAGES, TOOLS)))
    return [event for event in events if event.type == "usage"]


def _mock(body: bytes) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(200, content=body))


def test_openai_chat_reports_cached_prompt_tokens() -> None:
    body = _sse(
        '{"choices":[],"usage":{"prompt_tokens":2112,"completion_tokens":2,"total_tokens":2114,'
        '"prompt_tokens_details":{"cached_tokens":2048}}}',
        "[DONE]",
    )
    provider = OpenAIProvider(api_key="test", transport=_mock(body))
    [usage] = _usage(provider, "o4-mini")
    assert (usage.prompt_tokens, usage.cache_read_tokens, usage.cache_write_tokens) == (2112, 2048, None)


def test_openai_responses_reports_cached_input_tokens() -> None:
    body = _sse(
        '{"type":"response.completed","response":{"usage":{"input_tokens":3000,"output_tokens":5,'
        '"total_tokens":3005,"input_tokens_details":{"cached_tokens":2944}}}}',
    )
    provider = OpenAIProvider(api_key="test", transport=_mock(body))
    [usage] = _usage(provider, "gpt-5.4")
    assert (usage.prompt_tokens, usage.cache_read_tokens) == (3000, 2944)


def test_anthropic_prompt_tokens_include_cache_reads_and_writes() -> None:
    body = _sse(
        '{"type":"message_start","message":{"usage":{"input_tokens":12,'
        '"cache_read_input_tokens":4000,"cache_creation_input_tokens":300,"output_tokens":1}}}',
        '{"type":"message_delta","usage":{"output_tokens":9}}',
    )
    provider = AnthropicProvider(api_key="test", transport=_mock(body))
    start, delta = _usage(provider, "claude-test")
    assert (start.prompt_tokens, start.cache_read_tokens, start.cache_write_tokens) == (4312, 4000, 300)
    assert delta.completion_tokens == 9


def test_gemini_reports_cached_content_tokens() -> None:
    body = _sse(
        '{"candidates":[{"content":{"parts":[{"text":"Hi"}]}}],"usageMetadata":{"promptTokenCount":5000,'
        '"cachedContentTokenCount":4096,"candidatesTokenCount":3,"totalTokenCount":5003}}',
    )
    provider = GeminiProvider(api_key="test", transport=_mock(body))
    [usage] = _usage(provider, "gemini-test")
    assert (usage.prompt_tokens, usage.cache_read_tokens) == (5000, 4096)


def _sent_payloads(provider_type: type[OpenAIProvider], model: str, systems: List[str]) -> List[dict]:
    sent: List[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, content=_sse("[DONE]"))

    provider = provider_type(api_key="test", transport=httpx.MockTransport(handler))
    for system in systems:
        messages = [Message(role="system", content=system), Message(role="user", content=f"turn for {system}")]
        asyncio.run(_drain(provider.stream(model, messages, TOOLS)))
    return sent


@pytest.mark.parametrize("model", ["o4-mini", "gpt-5.4"])
def test_openai_prompt_cache_key_follows_the_stable_prefix(model: str) -> None:
    first, second, changed = _sent_payloads(OpenAIProvider, model, ["Be brief", "Be brief", "Be verbose"])
    assert first["prompt_cache_key"] == second["prompt_cache_key"]
    assert first["prompt_cache_key"] != changed["prompt_cache_key"]
    assert first["prompt_cache_key"].startswith("symphony-")
    assert len(first["prompt_cache_key"]) <= 64


@pytest.mark.parametrize("provider_type", [GrokProvider, OllamaProvider])
def test_compatible_servers_get_no_prompt_cache_key(provider_type: type[OpenAIProvider]) -> None:
    [payload] = _sent_payloads(provider_type, "grok-4.6", ["Be brief"])
    assert "prompt_cache_key" not in payload


def test_turn_cost_bills_cached_input_at_the_cache_rates() -> None:
    register_model(
        ModelInfo(
            id="priced-cache",
            provider="anthropic",
            api="messages",
            price=ModelPrice(input=3.0, output=15.0, cache_read=0.3, cache_write=3.75),
        )
    )
    try:
        # 1M prompt tokens: 600k read from cache, 100k written, 300k fresh.
        cost = turn_cost(
            "anthropic:priced-cache",
            input_tokens=1_000_000,
            output_tokens=100_000,
            cache_read_tokens=600_000,
            cache_write_tokens=100_000,
        )
        assert cost == pytest.approx(0.3 * 3.0 + 0.1 * 15.0 + 0.6 * 0.3 + 0.1 * 3.75)
        assert turn_cost("anthropic:priced-cache", input_tokens=1_000_000, output_tokens=0) == 3.0
    finally:
        unregister_model("anthropic", "priced-cache")


def test_turn_cost_falls_back_to_the_input_rate_without_cache_prices() -> None:
    register_model(
        ModelInfo(id="priced-plain", provider="openai", api="responses", price=ModelPrice(input=2.0, output=8.0))
    )
    try:
        assert turn_cost(
            "openai:priced-plain", input_tokens=1_000_000, output_tokens=0, cache_read_tokens=500_000
        ) == pytest.approx(2.0)
    finally:
        unregister_model("openai", "priced-plain")
