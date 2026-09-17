from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from core_ai.models import get_model, unregister_model
from core_ai.providers.catalog import configured_provider_ids, find_provider, provider_api_key
from core_ai.providers.defaults import build_default_registry, default_model_id
from core_ai.providers.vercel import (
    VERCEL_DEFAULT_BASE_URL,
    VercelProvider,
    discover_vercel_models,
    is_evaluation_model,
    vercel_chat_base_url,
    vercel_model_ids,
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


def test_vercel_chat_base_url_normalizes() -> None:
    assert vercel_chat_base_url("") == VERCEL_DEFAULT_BASE_URL
    assert vercel_chat_base_url("https://ai-gateway.vercel.sh") == VERCEL_DEFAULT_BASE_URL
    assert vercel_chat_base_url("https://ai-gateway.vercel.sh/v1") == VERCEL_DEFAULT_BASE_URL


def test_vercel_stream_uses_chat_completions() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content)
        captured["authorization"] = request.headers.get("authorization")
        body = "\n\n".join(
            (
                'data: {"choices":[{"index":0,"delta":{"content":"Hi"}}]}',
                "data: [DONE]",
            )
        )
        return httpx.Response(200, text=body)

    async def collect() -> list[StreamEvent]:
        provider = VercelProvider(
            api_key="gw-key",
            transport=httpx.MockTransport(handler),
        )
        return [
            event
            async for event in provider.stream(
                "anthropic/claude-sonnet-5",
                [Message(role="user", content="Hi")],
                max_output_tokens=128,
                reasoning_effort="high",
            )
        ]

    events = asyncio.run(collect())
    payload = captured["payload"]
    assert captured["path"] == "/v1/chat/completions"
    assert captured["authorization"] == "Bearer gw-key"
    assert payload["model"] == "anthropic/claude-sonnet-5"
    assert payload["stream_options"] == {"include_usage": True}
    assert payload["max_tokens"] == 128
    assert "max_completion_tokens" not in payload
    assert "reasoning_effort" not in payload
    assert events[0].delta == "Hi"
    assert events[-1].type == "done"


def test_discover_vercel_models_lists_ids() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(
            200,
            json={"data": [{"id": "openai/gpt-4o"}, {"id": "anthropic/claude-sonnet-5"}]},
        )

    names = discover_vercel_models(
        api_key="gw-key",
        transport=httpx.MockTransport(handler),
    )
    assert names == ["openai/gpt-4o", "anthropic/claude-sonnet-5"]


def test_vercel_model_ids_keeps_evaluation_models() -> None:
    names = vercel_model_ids(
        {
            "data": [
                {"id": "openai/gpt-4o", "type": "language"},
                {"id": "typesafe-ai/jev", "type": "evaluation"},
                {"id": "openai/text-embedding-3-small", "type": "embedding"},
            ]
        }
    )
    assert names == ["openai/gpt-4o", "typesafe-ai/jev"]


def test_is_evaluation_model_detects_typesafe_jev() -> None:
    assert is_evaluation_model("typesafe-ai/jev") is True
    assert is_evaluation_model("anthropic/claude-sonnet-5") is False


def test_vercel_evaluation_model_uses_evaluation_generation_api() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content)
        captured["headers"] = dict(request.headers)
        return httpx.Response(
            200,
            json={
                "answers": {
                    "response": {"type": "boolean", "probability": 0.91},
                },
                "usage": {"inputTokens": 12, "outputTokens": 3},
            },
        )

    async def collect() -> list[StreamEvent]:
        provider = VercelProvider(
            api_key="gw-key",
            transport=httpx.MockTransport(handler),
        )
        return [
            event
            async for event in provider.stream(
                "typesafe-ai/jev",
                [Message(role="user", content="Should we keep helping?")],
            )
        ]

    events = asyncio.run(collect())
    payload = captured["payload"]
    headers = captured["headers"]
    assert captured["path"] == "/v1/evaluation-model"
    assert payload["state"] == "user: Should we keep helping?"
    assert payload["questions"]["response"]["type"] == "boolean"
    assert headers["ai-model-id"] == "typesafe-ai/jev"
    assert headers["ai-evaluation-model-specification-version"] == "4"
    assert [(event.type, event.delta) for event in events if event.type != "usage"] == [
        ("text_delta", "true"),
        ("done", None),
    ]
    usage = next(event for event in events if event.type == "usage")
    assert usage.prompt_tokens == 12
    assert usage.completion_tokens == 3
    assert usage.total_tokens == 15


def test_vercel_evaluation_model_accepts_explicit_questions() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"answers": {"department": {"type": "choice", "choice": "billing"}}},
        )

    async def collect() -> list[StreamEvent]:
        provider = VercelProvider(
            api_key="gw-key",
            transport=httpx.MockTransport(handler),
        )
        questions = {
            "state": {"message": "I was charged twice."},
            "questions": {
                "department": {
                    "type": "choice",
                    "instructions": "Which team should handle this?",
                    "criteria": {"billing": "Payments", "support": "Other"},
                }
            },
        }
        return [
            event
            async for event in provider.stream(
                "typesafe-ai/jev",
                [Message(role="user", content=json.dumps(questions))],
            )
        ]

    events = asyncio.run(collect())
    payload = captured["payload"]
    assert payload["state"] == {"message": "I was charged twice."}
    assert payload["questions"]["department"]["type"] == "choice"
    assert events[0].delta == "billing"


def test_vercel_evaluation_model_emits_tool_call_for_chosen_tool() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"answers": {"next_action": {"type": "choice", "choice": "search"}}},
        )

    async def collect() -> list[StreamEvent]:
        provider = VercelProvider(
            api_key="gw-key",
            transport=httpx.MockTransport(handler),
        )
        return [
            event
            async for event in provider.stream(
                "typesafe-ai/jev",
                [Message(role="user", content="Find the relevant files.")],
                tools=[{"name": "search", "description": "Search the workspace"}],
            )
        ]

    events = asyncio.run(collect())
    payload = captured["payload"]
    assert payload["questions"]["next_action"]["criteria"]["search"] == (
        "Search the workspace"
    )
    assert [(event.type, event.tool_name, event.delta) for event in events] == [
        ("toolcall_start", "search", None),
        ("toolcall_delta", None, "{}"),
        ("done", None, None),
    ]


def test_vercel_registers_from_ai_gateway_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "gw-key")
    monkeypatch.setenv("VERCEL_MODEL", "openai/gpt-4o")
    monkeypatch.setattr(
        "core_ai.providers.defaults.discover_vercel_models",
        lambda *args, **kwargs: ["anthropic/claude-sonnet-5"],
    )
    try:
        assert configured_provider_ids() == ("vercel",)
        registry = build_default_registry()
        assert registry.namespaces() == ("vercel",)
        assert isinstance(registry._providers["vercel"], VercelProvider)
        assert registry._providers["vercel"].base_url == VERCEL_DEFAULT_BASE_URL
        assert get_model("vercel", "openai/gpt-4o") is not None
        assert get_model("vercel", "anthropic/claude-sonnet-5") is not None
        assert default_model_id(registry) == "vercel:openai/gpt-4o"
    finally:
        unregister_model("vercel", "openai/gpt-4o")
        unregister_model("vercel", "anthropic/claude-sonnet-5")


def test_vercel_registers_from_alias_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERCEL_AI_GATEWAY_API_KEY", "alias-key")
    monkeypatch.setattr(
        "core_ai.providers.defaults.discover_vercel_models",
        lambda *args, **kwargs: [],
    )
    try:
        from core_ai.providers.catalog import get_provider

        spec = get_provider("vercel")
        assert provider_api_key(spec) == "alias-key"
        registry = build_default_registry()
        assert registry.namespaces() == ("vercel",)
        assert default_model_id(registry) == "vercel:openai/gpt-4o"
    finally:
        unregister_model("vercel", "openai/gpt-4o")


def test_find_provider_matches_vercel() -> None:
    assert find_provider("vercel").id == "vercel"  # type: ignore[union-attr]
    assert find_provider("Vercel").id == "vercel"  # type: ignore[union-attr]
    assert find_provider("ai_gateway").id == "vercel"  # type: ignore[union-attr]
    assert find_provider("AI_GATEWAY_API_KEY").id == "vercel"  # type: ignore[union-attr]
