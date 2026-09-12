from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from core_ai.models import get_model, unregister_model
from core_ai.providers.catalog import configured_provider_ids, find_provider
from core_ai.providers.defaults import build_default_registry, default_model_id
from core_ai.providers.ollama import (
    OLLAMA_DEFAULT_BASE_URL,
    OllamaProvider,
    discover_ollama_models,
    ollama_chat_base_url,
    ollama_native_base_url,
)
from core_ai.types import Message, StreamEvent

LOCAL_PROVIDER_ENV = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "XAI_API_KEY",
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
    for name in LOCAL_PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)


def test_ollama_chat_base_url_normalizes_host_and_v1() -> None:
    assert ollama_chat_base_url("") == OLLAMA_DEFAULT_BASE_URL
    assert ollama_chat_base_url("localhost:11434") == "http://localhost:11434/v1"
    assert ollama_chat_base_url("http://127.0.0.1:11434") == "http://127.0.0.1:11434/v1"
    assert ollama_chat_base_url("http://127.0.0.1:11434/v1") == "http://127.0.0.1:11434/v1"
    assert ollama_native_base_url("http://localhost:11434/v1") == "http://localhost:11434"


def test_ollama_stream_uses_chat_completions_compat_payload() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content)
        body = "\n\n".join(
            (
                'data: {"choices":[{"index":0,"delta":{"content":"Hi"}}]}',
                "data: [DONE]",
            )
        )
        return httpx.Response(200, text=body)

    async def collect() -> list[StreamEvent]:
        provider = OllamaProvider(transport=httpx.MockTransport(handler))
        return [
            event
            async for event in provider.stream(
                "qwen2.5-coder:7b",
                [Message(role="user", content="Hi")],
                max_output_tokens=64,
                reasoning_effort="high",
            )
        ]

    events = asyncio.run(collect())
    payload = captured["payload"]
    assert captured["path"] == "/v1/chat/completions"
    assert payload["model"] == "qwen2.5-coder:7b"
    assert "stream_options" not in payload
    assert payload["max_tokens"] == 64
    assert "max_completion_tokens" not in payload
    assert "reasoning_effort" not in payload
    assert events[0].delta == "Hi"
    assert events[-1].type == "done"


def test_discover_ollama_models_uses_native_tags_and_skips_embeddings() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(
            200,
            json={
                "models": [
                    {"name": "qwen2.5-coder:7b"},
                    {"name": "nomic-embed-text:latest"},
                    {"model": "llama3.1:8b"},
                ]
            },
        )

    names = discover_ollama_models(transport=httpx.MockTransport(handler))
    assert names == ["qwen2.5-coder:7b", "llama3.1:8b"]


def test_discover_ollama_models_falls_back_to_openai_models() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(404)
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "llama3.1"}, {"id": "all-minilm-embed"}]})

    names = discover_ollama_models(transport=httpx.MockTransport(handler))
    assert names == ["llama3.1"]


def test_discover_ollama_models_returns_empty_when_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    assert discover_ollama_models(transport=httpx.MockTransport(handler)) == []


def test_build_default_registry_does_not_probe_ollama_without_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []

    def fake_discover(base_url: str, **kwargs: object) -> list[str]:
        called.append(base_url)
        return ["should-not-run"]

    monkeypatch.setattr(
        "core_ai.providers.defaults.discover_ollama_models", fake_discover
    )
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    registry = build_default_registry()
    assert registry.namespaces() == ("openai",)
    assert called == []


def test_ollama_opt_in_via_enabled_registers_discovered_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OLLAMA_ENABLED", "1")
    monkeypatch.setattr(
        "core_ai.providers.defaults.discover_ollama_models",
        lambda *args, **kwargs: ["qwen2.5-coder:7b"],
    )
    try:
        registry = build_default_registry()
        assert registry.namespaces() == ("ollama",)
        assert isinstance(registry._providers["ollama"], OllamaProvider)
        assert get_model("ollama", "qwen2.5-coder:7b") is not None
        assert default_model_id(registry) == "ollama:qwen2.5-coder:7b"
        assert configured_provider_ids() == ("ollama",)
    finally:
        unregister_model("ollama", "qwen2.5-coder:7b")


def test_ollama_host_env_opts_in_and_prefers_ollama_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "mistral")
    monkeypatch.setattr(
        "core_ai.providers.defaults.discover_ollama_models",
        lambda *args, **kwargs: ["qwen2.5-coder:7b"],
    )
    try:
        registry = build_default_registry()
        assert registry.namespaces() == ("ollama",)
        assert registry._providers["ollama"].base_url == "http://127.0.0.1:11434/v1"
        assert default_model_id(registry) == "ollama:mistral"
        assert get_model("ollama", "mistral") is not None
        assert get_model("ollama", "qwen2.5-coder:7b") is not None
    finally:
        unregister_model("ollama", "mistral")
        unregister_model("ollama", "qwen2.5-coder:7b")


def test_ollama_model_colon_tag_is_not_treated_as_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OLLAMA_ENABLED", "1")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5-coder:7b")
    monkeypatch.setattr(
        "core_ai.providers.defaults.discover_ollama_models",
        lambda *args, **kwargs: ["mistral"],
    )
    try:
        registry = build_default_registry()
        assert get_model("ollama", "qwen2.5-coder:7b") is not None
        assert get_model("ollama", "7b") is None
        assert default_model_id(registry) == "ollama:qwen2.5-coder:7b"
    finally:
        unregister_model("ollama", "qwen2.5-coder:7b")
        unregister_model("ollama", "mistral")


def test_ollama_model_keeps_provider_prefix_and_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OLLAMA_ENABLED", "1")
    monkeypatch.setenv("OLLAMA_MODEL", "ollama:qwen2.5-coder:7b")
    monkeypatch.setattr(
        "core_ai.providers.defaults.discover_ollama_models",
        lambda *args, **kwargs: [],
    )
    try:
        registry = build_default_registry()
        assert get_model("ollama", "qwen2.5-coder:7b") is not None
        assert default_model_id(registry) == "ollama:qwen2.5-coder:7b"
    finally:
        unregister_model("ollama", "qwen2.5-coder:7b")


def test_find_provider_matches_ollama() -> None:
    assert find_provider("ollama").id == "ollama"  # type: ignore[union-attr]
    assert find_provider("Ollama").id == "ollama"  # type: ignore[union-attr]
