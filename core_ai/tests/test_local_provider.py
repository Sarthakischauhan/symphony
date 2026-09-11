from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from core_ai.models import get_model, unregister_model
from core_ai.providers.catalog import configured_provider_ids, find_provider
from core_ai.providers.defaults import build_default_registry, default_model_id
from core_ai.providers.local import LocalProvider, discover_local_models, local_chat_base_url
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


def test_local_chat_base_url_requires_a_value() -> None:
    assert local_chat_base_url("") == ""
    assert local_chat_base_url("127.0.0.1:1234") == "http://127.0.0.1:1234/v1"
    assert local_chat_base_url("http://127.0.0.1:8080/v1") == "http://127.0.0.1:8080/v1"


def test_local_stream_uses_chat_completions_compat_payload() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["auth"] = request.headers.get("authorization")
        captured["payload"] = json.loads(request.content)
        body = "\n\n".join(
            (
                'data: {"choices":[{"index":0,"delta":{"content":"Hi"}}]}',
                "data: [DONE]",
            )
        )
        return httpx.Response(200, text=body)

    async def collect() -> list[StreamEvent]:
        provider = LocalProvider(
            api_key="secret",
            base_url="http://127.0.0.1:1234",
            transport=httpx.MockTransport(handler),
        )
        return [
            event
            async for event in provider.stream(
                "qwen2.5-coder",
                [Message(role="user", content="Hi")],
                max_output_tokens=32,
            )
        ]

    events = asyncio.run(collect())
    payload = captured["payload"]
    assert captured["path"] == "/v1/chat/completions"
    assert captured["auth"] == "Bearer secret"
    assert payload["model"] == "qwen2.5-coder"
    assert "stream_options" not in payload
    assert payload["max_tokens"] == 32
    assert events[0].delta == "Hi"


def test_discover_local_models_reads_openai_models() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        assert request.headers.get("authorization") == "Bearer local"
        return httpx.Response(
            200,
            json={"data": [{"id": "llama-3.1-8b"}, {"id": "text-embedding-nomic"}]},
        )

    names = discover_local_models(
        "http://127.0.0.1:1234/v1",
        transport=httpx.MockTransport(handler),
    )
    assert names == ["llama-3.1-8b"]


def test_local_api_key_alone_does_not_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_API_KEY", "secret")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    called: list[str] = []

    def fake_discover(base_url: str, **kwargs: object) -> list[str]:
        called.append(base_url)
        return ["should-not-run"]

    monkeypatch.setattr("core_ai.providers.defaults.discover_local_models", fake_discover)
    registry = build_default_registry()
    assert registry.namespaces() == ("openai",)
    assert called == []
    assert configured_provider_ids() == ("openai",)


def test_local_base_url_opts_in_and_registers_discovered_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_BASE_URL", "http://127.0.0.1:1234")
    monkeypatch.setenv("LOCAL_MODEL", "qwen2.5-coder")
    monkeypatch.setattr(
        "core_ai.providers.defaults.discover_local_models",
        lambda *args, **kwargs: ["llama-3.1-8b"],
    )
    try:
        registry = build_default_registry()
        assert registry.namespaces() == ("local",)
        assert isinstance(registry._providers["local"], LocalProvider)
        assert registry._providers["local"].base_url == "http://127.0.0.1:1234/v1"
        assert get_model("local", "qwen2.5-coder") is not None
        assert get_model("local", "llama-3.1-8b") is not None
        assert default_model_id(registry) == "local:qwen2.5-coder"
        assert configured_provider_ids() == ("local",)
    finally:
        unregister_model("local", "qwen2.5-coder")
        unregister_model("local", "llama-3.1-8b")


def test_find_provider_matches_local() -> None:
    assert find_provider("local").id == "local"  # type: ignore[union-attr]
    assert find_provider("Local").id == "local"  # type: ignore[union-attr]
