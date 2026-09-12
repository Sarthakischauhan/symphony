"""Static catalog of supported model providers and their credentials."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    label: str
    description: str
    env_key: str
    default_model: str
    docs_url: str
    key_placeholder: str
    env_aliases: tuple[str, ...] = ()
    default_base_url: str = ""
    base_url_env: str = ""
    requires_key: bool = True
    default_api_key: str = ""
    host_env: str = ""
    enabled_env: str = ""


class MissingProviderCredentials(RuntimeError):
    """Raised when no provider API key is available."""

    def __init__(self) -> None:
        super().__init__(
            "Set OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY / GOOGLE_API_KEY, "
            "or XAI_API_KEY, or opt in to Ollama / a local OpenAI-compatible server"
        )


PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        id="openai",
        label="OpenAI",
        description="GPT-5.6 and the Responses API",
        env_key="OPENAI_API_KEY",
        default_model="openai:gpt-5.6-luna",
        docs_url="https://platform.openai.com/api-keys",
        key_placeholder="sk-...",
        default_base_url="https://api.openai.com/v1",
        base_url_env="OPENAI_BASE_URL",
    ),
    ProviderSpec(
        id="anthropic",
        label="Anthropic",
        description="Claude Sonnet, Opus, and Haiku",
        env_key="ANTHROPIC_API_KEY",
        default_model="anthropic:claude-sonnet-5",
        docs_url="https://console.anthropic.com/settings/keys",
        key_placeholder="sk-ant-...",
        default_base_url="https://api.anthropic.com",
        base_url_env="ANTHROPIC_BASE_URL",
    ),
    ProviderSpec(
        id="gemini",
        label="Gemini",
        description="Gemini 3.7 Flash and Pro",
        env_key="GEMINI_API_KEY",
        default_model="gemini:gemini-3.7-flash",
        docs_url="https://aistudio.google.com/apikey",
        key_placeholder="AIza...",
        env_aliases=("GOOGLE_API_KEY",),
        default_base_url="https://generativelanguage.googleapis.com/v1beta",
        base_url_env="GEMINI_BASE_URL",
    ),
    ProviderSpec(
        id="grok",
        label="Grok",
        description="Grok 4 and the xAI API",
        env_key="XAI_API_KEY",
        default_model="grok:grok-4.6",
        docs_url="https://console.x.ai/",
        key_placeholder="xai-...",
        default_base_url="https://api.x.ai/v1",
        base_url_env="XAI_BASE_URL",
    ),
    ProviderSpec(
        id="ollama",
        label="Ollama",
        description="Local models via Ollama (OpenAI-compatible)",
        env_key="OLLAMA_API_KEY",
        default_model="ollama:llama3.1",
        docs_url="https://ollama.com",
        key_placeholder="http://localhost:11434/v1",
        default_base_url="http://localhost:11434/v1",
        base_url_env="OLLAMA_BASE_URL",
        requires_key=False,
        default_api_key="ollama",
        host_env="OLLAMA_HOST",
        enabled_env="OLLAMA_ENABLED",
    ),
    ProviderSpec(
        id="local",
        label="Local",
        description="LM Studio, vLLM, llama.cpp, or SGLang",
        env_key="LOCAL_API_KEY",
        default_model="local:local-model",
        docs_url="https://lmstudio.ai",
        key_placeholder="http://127.0.0.1:1234/v1",
        default_base_url="",
        base_url_env="LOCAL_BASE_URL",
        requires_key=False,
        default_api_key="local",
    ),
)


def get_provider(provider_id: str) -> ProviderSpec:
    for spec in PROVIDERS:
        if spec.id == provider_id:
            return spec
    raise KeyError(f"Unknown provider: {provider_id}")


def find_provider(value: str) -> Optional[ProviderSpec]:
    needle = value.strip().lower()
    if not needle:
        return None
    matches = [
        spec
        for spec in PROVIDERS
        if needle in {
            spec.id,
            spec.label.lower(),
            spec.env_key.lower(),
            spec.env_key.lower().removesuffix("_api_key"),
        }
    ]
    return matches[0] if len(matches) == 1 else None


def provider_api_key(
    spec: ProviderSpec,
    environ: Mapping[str, str] | None = None,
) -> Optional[str]:
    env = os.environ if environ is None else environ
    for name in (spec.env_key, *spec.env_aliases):
        value = (env.get(name) or "").strip()
        if value:
            return value
    return None


def provider_is_configured(
    spec: ProviderSpec,
    environ: Mapping[str, str] | None = None,
) -> bool:
    env = os.environ if environ is None else environ
    if spec.requires_key:
        return bool(provider_api_key(spec, env))
    if spec.base_url_env and (env.get(spec.base_url_env) or "").strip():
        return True
    if spec.host_env and (env.get(spec.host_env) or "").strip():
        return True
    if spec.enabled_env and _env_flag(env.get(spec.enabled_env)):
        return True
    if spec.default_base_url and provider_api_key(spec, env):
        return True
    return False


def configured_provider_ids(environ: Mapping[str, str] | None = None) -> tuple[str, ...]:
    return tuple(spec.id for spec in PROVIDERS if provider_is_configured(spec, environ))


def has_configured_provider(environ: Mapping[str, str] | None = None) -> bool:
    return bool(configured_provider_ids(environ))


def _env_flag(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}
