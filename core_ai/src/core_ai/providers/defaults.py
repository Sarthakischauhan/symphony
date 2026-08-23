from __future__ import annotations

import os
from typing import Optional

from core_ai.providers.anthropic import AnthropicProvider
from core_ai.providers.gemini import GeminiProvider
from core_ai.providers.openai import OpenAIProvider
from core_ai.registry import ModelRegistry

DEFAULT_MODELS = {
    "openai": "openai:gpt-5.6-luna",
    "anthropic": "anthropic:claude-sonnet-5",
    "gemini": "gemini:gemini-3.7-flash",
}


def build_default_registry(
    *,
    openai_api_key: Optional[str] = None,
    anthropic_api_key: Optional[str] = None,
    gemini_api_key: Optional[str] = None,
    openai_base_url: Optional[str] = None,
    anthropic_base_url: Optional[str] = None,
    gemini_base_url: Optional[str] = None,
) -> ModelRegistry:
    """Register every provider that has credentials in the environment."""
    openai_api_key = openai_api_key if openai_api_key is not None else os.getenv("OPENAI_API_KEY")
    anthropic_api_key = (
        anthropic_api_key if anthropic_api_key is not None else os.getenv("ANTHROPIC_API_KEY")
    )
    gemini_api_key = gemini_api_key if gemini_api_key is not None else (
        os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    )
    registry = ModelRegistry()
    if openai_api_key:
        registry.register(
            "openai",
            OpenAIProvider(
                api_key=openai_api_key,
                base_url=openai_base_url
                or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            ),
        )
    if anthropic_api_key:
        registry.register(
            "anthropic",
            AnthropicProvider(
                api_key=anthropic_api_key,
                base_url=anthropic_base_url
                or os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
            ),
        )
    if gemini_api_key:
        registry.register(
            "gemini",
            GeminiProvider(
                api_key=gemini_api_key,
                base_url=gemini_base_url
                or os.getenv(
                    "GEMINI_BASE_URL",
                    "https://generativelanguage.googleapis.com/v1beta",
                ),
            ),
        )
    if not registry.namespaces():
        raise RuntimeError(
            "Set OPENAI_API_KEY, ANTHROPIC_API_KEY, or GEMINI_API_KEY / GOOGLE_API_KEY"
        )
    return registry


def default_model_id(registry: ModelRegistry, model_id: Optional[str] = None) -> str:
    """Resolve a `provider:model` id from an explicit value, env, or first provider."""
    selected = (
        model_id
        or os.getenv("SYMPHONY_MODEL")
        or os.getenv("OPENAI_MODEL")
        or os.getenv("ANTHROPIC_MODEL")
        or os.getenv("GEMINI_MODEL")
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
