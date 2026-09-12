from __future__ import annotations

import pytest

from core_ai.providers.anthropic import AnthropicProvider
from core_ai.providers.catalog import MissingProviderCredentials, configured_provider_ids, find_provider
from core_ai.providers.defaults import (
    _qualified_model_id,
    _unqualified_model,
    build_default_registry,
    default_model_id,
)
from core_ai.providers.gemini import GeminiProvider
from core_ai.providers.grok import GrokProvider
from core_ai.providers.openai import OpenAIProvider

PROVIDER_ENV = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "XAI_API_KEY",
    "SYMPHONY_MODEL",
    "OPENAI_MODEL",
    "ANTHROPIC_MODEL",
    "GEMINI_MODEL",
    "GROK_MODEL",
    "XAI_MODEL",
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


def test_build_default_registry_registers_available_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("XAI_API_KEY", "grok-key")

    registry = build_default_registry()

    assert registry.namespaces() == ("openai", "anthropic", "gemini", "grok")
    assert isinstance(registry._providers["openai"], OpenAIProvider)
    assert isinstance(registry._providers["anthropic"], AnthropicProvider)
    assert isinstance(registry._providers["gemini"], GeminiProvider)
    assert isinstance(registry._providers["grok"], GrokProvider)


def test_build_default_registry_requires_at_least_one_key() -> None:
    with pytest.raises(MissingProviderCredentials, match="OPENAI_API_KEY"):
        build_default_registry()
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        build_default_registry()


def test_default_model_id_prefers_first_registered_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")

    registry = build_default_registry()
    assert default_model_id(registry) == "anthropic:claude-sonnet-5"
    assert default_model_id(registry, "claude-opus-5") == "anthropic:claude-opus-5"
    assert default_model_id(registry, "gemini:gemini-3.7-flash") == "gemini:gemini-3.7-flash"


def test_gemini_google_api_key_alias_counts_as_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "google-key")

    assert configured_provider_ids() == ("gemini",)
    registry = build_default_registry()
    assert registry.namespaces() == ("gemini",)


def test_find_provider_matches_id_and_label() -> None:
    assert find_provider("anthropic").id == "anthropic"  # type: ignore[union-attr]
    assert find_provider("OpenAI").id == "openai"  # type: ignore[union-attr]
    assert find_provider("grok").id == "grok"  # type: ignore[union-attr]
    assert find_provider("xai").id == "grok"  # type: ignore[union-attr]
    assert find_provider("ollama").id == "ollama"  # type: ignore[union-attr]
    assert find_provider("local").id == "local"  # type: ignore[union-attr]
    assert find_provider("missing") is None


def test_grok_registers_from_xai_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XAI_API_KEY", "xai-key")

    assert configured_provider_ids() == ("grok",)
    registry = build_default_registry()
    assert registry.namespaces() == ("grok",)
    assert isinstance(registry._providers["grok"], GrokProvider)
    assert default_model_id(registry) == "grok:grok-4.6"


def test_unqualified_model_strips_known_provider_prefix_only() -> None:
    assert _unqualified_model("qwen2.5-coder:7b") == "qwen2.5-coder:7b"
    assert _unqualified_model("ollama:qwen2.5-coder:7b") == "qwen2.5-coder:7b"
    assert _unqualified_model("local:llama-3.1-8b") == "llama-3.1-8b"
    assert _unqualified_model("mistral") == "mistral"
    assert _unqualified_model("openai:gpt-5.6-luna") == "gpt-5.6-luna"
    assert _unqualified_model(None) == ""
    assert _unqualified_model("  ") == ""


def test_qualified_model_id_prefixes_unknown_colon_tags() -> None:
    assert _qualified_model_id("qwen2.5-coder:7b", ("ollama",)) == "ollama:qwen2.5-coder:7b"
    assert _qualified_model_id("ollama:qwen2.5-coder:7b", ("ollama",)) == "ollama:qwen2.5-coder:7b"
    assert _qualified_model_id("mistral", ("ollama",)) == "ollama:mistral"
    assert _qualified_model_id("openai:gpt-5.6-luna", ("anthropic",)) == "openai:gpt-5.6-luna"
    assert _qualified_model_id("claude-opus-5", ("anthropic",)) == "anthropic:claude-opus-5"
    assert _qualified_model_id("qwen2.5-coder:7b", ("openai", "ollama")) == (
        "openai:qwen2.5-coder:7b"
    )
