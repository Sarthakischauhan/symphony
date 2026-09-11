from __future__ import annotations

import os
from typing import Optional

from core_ai.models import ModelInfo, list_models, register_model, unregister_model
from core_ai.providers.anthropic import AnthropicProvider
from core_ai.providers.catalog import (
    PROVIDERS,
    MissingProviderCredentials,
    ProviderSpec,
    provider_api_key,
    provider_is_configured,
)
from core_ai.providers.gemini import GeminiProvider
from core_ai.providers.grok import GrokProvider
from core_ai.providers.local import LocalProvider, discover_local_models, local_chat_base_url
from core_ai.providers.ollama import (
    OllamaProvider,
    discover_ollama_models,
    ollama_chat_base_url,
)
from core_ai.providers.openai import OpenAIProvider
from core_ai.registry import ModelRegistry

DEFAULT_MODELS = {spec.id: spec.default_model for spec in PROVIDERS}

_PROVIDER_TYPES = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
    "grok": GrokProvider,
    "ollama": OllamaProvider,
    "local": LocalProvider,
}

_MODEL_ENV = (
    "SYMPHONY_MODEL",
    "OPENAI_MODEL",
    "ANTHROPIC_MODEL",
    "GEMINI_MODEL",
    "GROK_MODEL",
    "XAI_MODEL",
    "OLLAMA_MODEL",
    "LOCAL_MODEL",
)


def build_default_registry(
    *,
    openai_api_key: Optional[str] = None,
    anthropic_api_key: Optional[str] = None,
    gemini_api_key: Optional[str] = None,
    grok_api_key: Optional[str] = None,
    ollama_api_key: Optional[str] = None,
    local_api_key: Optional[str] = None,
    openai_base_url: Optional[str] = None,
    anthropic_base_url: Optional[str] = None,
    gemini_base_url: Optional[str] = None,
    grok_base_url: Optional[str] = None,
    ollama_base_url: Optional[str] = None,
    local_base_url: Optional[str] = None,
) -> ModelRegistry:
    """Register every provider that has credentials in the environment."""
    explicit_keys = {
        "openai": openai_api_key,
        "anthropic": anthropic_api_key,
        "gemini": gemini_api_key,
        "grok": grok_api_key,
        "ollama": ollama_api_key,
        "local": local_api_key,
    }
    explicit_base_urls = {
        "openai": openai_base_url,
        "anthropic": anthropic_base_url,
        "gemini": gemini_base_url,
        "grok": grok_base_url,
        "ollama": ollama_base_url,
        "local": local_base_url,
    }
    registry = ModelRegistry()
    for spec in PROVIDERS:
        api_key = (
            explicit_keys[spec.id]
            if explicit_keys[spec.id] is not None
            else provider_api_key(spec)
        )
        explicit_url = explicit_base_urls[spec.id]
        opted_in = (
            explicit_keys[spec.id] is not None
            or explicit_url is not None
            or provider_is_configured(spec)
        )
        if spec.requires_key:
            if not api_key:
                continue
        elif not opted_in:
            continue
        if not api_key:
            api_key = spec.default_api_key
        base_url = _resolve_base_url(spec, explicit_url)
        if not spec.requires_key and not base_url:
            continue
        registry.register(
            spec.id,
            _PROVIDER_TYPES[spec.id](api_key=api_key, base_url=base_url),
        )
        _refresh_runtime_models(spec, base_url, api_key)
    if not registry.namespaces():
        raise MissingProviderCredentials()
    return registry


def default_model_id(registry: ModelRegistry, model_id: Optional[str] = None) -> str:
    """Resolve a `provider:model` id from an explicit value, env, or first provider."""
    selected = model_id
    if not selected:
        for name in _MODEL_ENV:
            value = os.getenv(name)
            if value:
                selected = value
                break
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
        if provider not in namespaces:
            continue
        runtime = list_models(provider)
        if provider in {"ollama", "local"} and runtime:
            return runtime[0].full_id
        return full_id
    raise RuntimeError("No model providers are registered")


def _resolve_base_url(spec: ProviderSpec, explicit: Optional[str]) -> str:
    if explicit is not None:
        raw = explicit
    else:
        raw = os.getenv(spec.base_url_env, "") if spec.base_url_env else ""
        if not raw and spec.host_env:
            raw = os.getenv(spec.host_env, "")
        if not raw:
            raw = spec.default_base_url
    if spec.id == "ollama":
        return ollama_chat_base_url(raw)
    if spec.id == "local":
        return local_chat_base_url(raw)
    return raw


def _refresh_runtime_models(spec: ProviderSpec, base_url: str, api_key: str) -> None:
    if spec.id == "ollama":
        discovered = discover_ollama_models(base_url)
        preferred = _unqualified_model(os.getenv("OLLAMA_MODEL"))
        _replace_runtime_models(spec.id, _merge_model_ids(preferred, discovered))
        return
    if spec.id == "local":
        discovered = discover_local_models(base_url, api_key=api_key)
        preferred = _unqualified_model(os.getenv("LOCAL_MODEL"))
        _replace_runtime_models(spec.id, _merge_model_ids(preferred, discovered))


def _replace_runtime_models(provider: str, model_ids: list[str]) -> None:
    for existing in list_models(provider):
        unregister_model(provider, existing.id)
    for model_id in model_ids:
        register_model(
            ModelInfo(id=model_id, provider=provider, api="chat_completions")
        )


def _merge_model_ids(preferred: str, discovered: list[str]) -> list[str]:
    ids: list[str] = []
    if preferred:
        ids.append(preferred)
    for model_id in discovered:
        if model_id not in ids:
            ids.append(model_id)
    return ids


def _unqualified_model(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if ":" in raw:
        return raw.split(":", 1)[1]
    return raw
