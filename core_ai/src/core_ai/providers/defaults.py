from __future__ import annotations

import os
from typing import Optional

from core_ai.providers.anthropic import AnthropicProvider
from core_ai.providers.catalog import (
    PROVIDERS,
    MissingProviderCredentials,
    provider_api_key,
)
from core_ai.providers.gemini import GeminiProvider
from core_ai.providers.grok import GrokProvider
from core_ai.providers.openai import OpenAIProvider
from core_ai.registry import ModelRegistry

DEFAULT_MODELS = {spec.id: spec.default_model for spec in PROVIDERS}

_PROVIDER_TYPES = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
    "grok": GrokProvider,
}


def build_default_registry(
    *,
    openai_api_key: Optional[str] = None,
    anthropic_api_key: Optional[str] = None,
    gemini_api_key: Optional[str] = None,
    grok_api_key: Optional[str] = None,
    openai_base_url: Optional[str] = None,
    anthropic_base_url: Optional[str] = None,
    gemini_base_url: Optional[str] = None,
    grok_base_url: Optional[str] = None,
) -> ModelRegistry:
    """Register every provider that has credentials in the environment."""
    explicit_keys = {
        "openai": openai_api_key,
        "anthropic": anthropic_api_key,
        "gemini": gemini_api_key,
        "grok": grok_api_key,
    }
    explicit_base_urls = {
        "openai": openai_base_url,
        "anthropic": anthropic_base_url,
        "gemini": gemini_base_url,
        "grok": grok_base_url,
    }
    registry = ModelRegistry()
    for spec in PROVIDERS:
        api_key = (
            explicit_keys[spec.id]
            if explicit_keys[spec.id] is not None
            else provider_api_key(spec)
        )
        if not api_key:
            continue
        base_url = explicit_base_urls[spec.id] or os.getenv(
            spec.base_url_env,
            spec.default_base_url,
        )
        registry.register(
            spec.id,
            _PROVIDER_TYPES[spec.id](api_key=api_key, base_url=base_url),
        )
    if not registry.namespaces():
        raise MissingProviderCredentials()
    return registry


def default_model_id(registry: ModelRegistry, model_id: Optional[str] = None) -> str:
    """Resolve a `provider:model` id from an explicit value, env, or first provider."""
    selected = (
        model_id
        or os.getenv("SYMPHONY_MODEL")
        or os.getenv("OPENAI_MODEL")
        or os.getenv("ANTHROPIC_MODEL")
        or os.getenv("GEMINI_MODEL")
        or os.getenv("GROK_MODEL")
        or os.getenv("XAI_MODEL")
    )
    namespaces = registry.namespaces()
    if selected:
        if ":" not in selected:
            provider = (
                "openai" if "openai" in namespaces
                else namespaces[0] if namespaces
                else "openai"
            )
            selected = f"{provider}:{selected}"
        return selected
    for provider, full_id in DEFAULT_MODELS.items():
        if provider in namespaces:
            return full_id
    raise RuntimeError("No model providers are registered")
