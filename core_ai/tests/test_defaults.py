from __future__ import annotations

import pytest

from core_ai.providers.anthropic import AnthropicProvider
from core_ai.providers.catalog import MissingProviderCredentials, configured_provider_ids, find_provider
from core_ai.providers.defaults import build_default_registry, default_model_id
from core_ai.providers.gemini import GeminiProvider
from core_ai.providers.openai import OpenAIProvider


def test_build_default_registry_registers_available_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")

    registry = build_default_registry()

    assert registry.namespaces() == ("openai", "anthropic", "gemini")
    assert isinstance(registry._providers["openai"], OpenAIProvider)
    assert isinstance(registry._providers["anthropic"], AnthropicProvider)
    assert isinstance(registry._providers["gemini"], GeminiProvider)


def test_build_default_registry_requires_at_least_one_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    with pytest.raises(MissingProviderCredentials, match="OPENAI_API_KEY"):
        build_default_registry()
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        build_default_registry()


def test_default_model_id_prefers_first_registered_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("SYMPHONY_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")

    registry = build_default_registry()
    assert default_model_id(registry) == "anthropic:claude-sonnet-5"
    assert default_model_id(registry, "claude-opus-5") == "anthropic:claude-opus-5"
    assert default_model_id(registry, "gemini:gemini-3.7-flash") == "gemini:gemini-3.7-flash"


def test_gemini_google_api_key_alias_counts_as_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "google-key")

    assert configured_provider_ids() == ("gemini",)
    registry = build_default_registry()
    assert registry.namespaces() == ("gemini",)


def test_find_provider_matches_id_and_label() -> None:
    assert find_provider("anthropic").id == "anthropic"  # type: ignore[union-attr]
    assert find_provider("OpenAI").id == "openai"  # type: ignore[union-attr]
    assert find_provider("missing") is None
