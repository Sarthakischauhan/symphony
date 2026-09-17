from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from core_ai.models import get_model, unregister_model
from core_ai.providers.catalog import configured_provider_ids, find_provider
from core_ai.providers.defaults import build_default_registry, default_model_id
from core_ai.providers.openrouter import (
    OPENROUTER_DEFAULT_BASE_URL,
    OpenRouterProvider,
    discover_openrouter_models,
    openrouter_chat_base_url,
)
from core_ai.types import Message, StreamEvent

PROVIDER_ENV = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "XAI_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENROUTER_BASE_URL",
    "OPENROUTER_MODEL",
    "OPENROUTER_HTTP_REFERER",
    "OPENROUTER_TITLE",
    "AI_GATEWAY_API_KEY",
    "VERCEL_AI_GATEWAY_API_KEY",
    "AI_GATEWAY_BASE_URL",
    "VERCEL_MODEL",
    "AI_GATEWAY_MODEL",
    "SYMPHONY_MODEL",
    "OLLAMA_API_KEY",
    "OLLAMA_BASE_URL",
    "OLLAMA_HOST",
    "OLLAMA_ENABLED",
    "OLLAMA_MODEL",
    "LOCAL_API_KEY",
    "LOCAL_BASE_URL",
    "LOCAL_MODEL",
)


@pytest.fixture(autouse=True)
def _isolate_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)


def test_openrouter_chat_base_url_normalizes() -> None:
    assert openrouter_chat_base_url("") == OPENROUTER_DEFAULT_BASE_URL
    assert openrouter_chat_base_url("https://openrouter.ai/api") == (
        "https://openrouter.ai/api/v1"
    )
    assert openrouter_chat_base_url("https://openrouter.ai/api/v1") == (
        "https://openrouter.ai/api/v1"
    )


def test_openrouter_stream_uses_chat_completions_and_attribution_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_HTTP_REFERER", "https://example.com")
    monkeypatch.setenv("OPENROUTER_TITLE", "Example App")
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content)
        captured["headers"] = dict(request.headers)
        body = "\n\n".join(
            (
                'data: {"choices":[{"index":0,"delta":{"content":"Hi"}}]}',
                "data: [DONE]",
            )
        )
        return httpx.Response(200, text=body)

    async def collect() -> list[StreamEvent]:
        provider = OpenRouterProvider(
            api_key="or-key",
            transport=httpx.MockTransport(handler),
        )
        return [
            event
            async for event in provider.stream(
                "openai/gpt-4o",
                [Message(role="user", content="Hi")],
                max_output_tokens=64,
                reasoning_effort="high",
            )
        ]

    events = asyncio.run(collect())
    payload = captured["payload"]
    headers = captured["headers"]
    assert captured["path"] == "/api/v1/chat/completions"
    assert payload["model"] == "openai/gpt-4o"
    assert payload["stream_options"] == {"include_usage": True}
    assert payload["max_tokens"] == 64
    assert "max_completion_tokens" not in payload
    assert "reasoning_effort" not in payload
    assert headers["http-referer"] == "https://example.com"
    assert headers["x-title"] == "Example App"
    assert headers["x-openrouter-title"] == "Example App"
    assert events[0].delta == "Hi"
    assert events[-1].type == "done"


def test_discover_openrouter_models_lists_ids() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/models"
        assert request.headers["authorization"] == "Bearer or-key"
        return httpx.Response(
            200,
            json={"data": [{"id": "openai/gpt-4o"}, {"id": "anthropic/claude-sonnet-4"}]},
        )

    names = discover_openrouter_models(
        api_key="or-key",
        transport=httpx.MockTransport(handler),
    )
    assert names == ["openai/gpt-4o", "anthropic/claude-sonnet-4"]


def test_openrouter_registers_from_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-4")
    monkeypatch.setattr(
        "core_ai.providers.defaults.discover_openrouter_models",
        lambda *args, **kwargs: ["openai/gpt-4o", "google/gemini-2.5-pro"],
    )
    try:
        assert configured_provider_ids() == ("openrouter",)
        registry = build_default_registry()
        assert registry.namespaces() == ("openrouter",)
        assert isinstance(registry._providers["openrouter"], OpenRouterProvider)
        assert registry._providers["openrouter"].base_url == OPENROUTER_DEFAULT_BASE_URL
        assert get_model("openrouter", "anthropic/claude-sonnet-4") is not None
        assert get_model("openrouter", "openai/gpt-4o") is not None
        assert default_model_id(registry) == "openrouter:anthropic/claude-sonnet-4"
    finally:
        unregister_model("openrouter", "anthropic/claude-sonnet-4")
        unregister_model("openrouter", "openai/gpt-4o")
        unregister_model("openrouter", "google/gemini-2.5-pro")


def test_find_provider_matches_openrouter() -> None:
    assert find_provider("openrouter").id == "openrouter"  # type: ignore[union-attr]
    assert find_provider("OpenRouter").id == "openrouter"  # type: ignore[union-attr]
    assert find_provider("OPENROUTER_API_KEY").id == "openrouter"  # type: ignore[union-attr]
