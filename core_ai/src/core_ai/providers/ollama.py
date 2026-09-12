"""Ollama via the OpenAI-compatible Chat Completions API.

Matches pi-ai: `api: openai-completions`, `baseUrl: http://localhost:11434/v1`,
dummy key, no `stream_options`, `max_tokens` instead of `max_completion_tokens`.
Models are discovered at registry build from `/api/tags` (fallback `/v1/models`).
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

import httpx

from core_ai.providers.openai import OpenAIProvider, openai_compat_base_url

OLLAMA_DEFAULT_HOST = "http://localhost:11434"
OLLAMA_DEFAULT_BASE_URL = "http://localhost:11434/v1"
OLLAMA_DUMMY_KEY = "ollama"
DISCOVER_TIMEOUT = 2.0


class OllamaProvider(OpenAIProvider):
    """Local Ollama daemon over Chat Completions."""

    include_stream_options = False
    max_tokens_field = "max_tokens"

    def __init__(
        self,
        api_key: str = OLLAMA_DUMMY_KEY,
        base_url: str = OLLAMA_DEFAULT_BASE_URL,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        super().__init__(
            api_key=api_key or OLLAMA_DUMMY_KEY,
            base_url=ollama_chat_base_url(base_url),
            transport=transport,
        )

    @staticmethod
    def _uses_chat_completions(model_name: str) -> bool:
        return True

    @staticmethod
    def _is_reasoning_model(model_name: str) -> bool:
        return False

    async def generate_image(
        self,
        model_name: str,
        prompt: str,
        output_format: str = "png",
    ) -> tuple[bytes, str]:
        del model_name, prompt, output_format
        raise NotImplementedError("OllamaProvider does not support image generation")


def ollama_chat_base_url(value: str = "") -> str:
    return openai_compat_base_url(value, default=OLLAMA_DEFAULT_HOST)


def ollama_native_base_url(openai_url: str) -> str:
    """Strip a trailing `/v1` so native Ollama routes like `/api/tags` resolve."""
    raw = (openai_url or "").rstrip("/")
    if raw.endswith("/v1"):
        return raw[: -len("/v1")] or OLLAMA_DEFAULT_HOST
    return raw or OLLAMA_DEFAULT_HOST


def discover_ollama_models(
    base_url: str = OLLAMA_DEFAULT_BASE_URL,
    *,
    timeout: float = DISCOVER_TIMEOUT,
    transport: Optional[httpx.BaseTransport] = None,
) -> list[str]:
    """List locally pulled chat models. Never raises; returns [] if Ollama is down."""
    chat_url = ollama_chat_base_url(base_url)
    native = ollama_native_base_url(chat_url)
    try:
        with httpx.Client(transport=transport, timeout=timeout) as client:
            names = _from_tags(client, native)
            if names:
                return names
            return _from_openai_models(client, chat_url)
    except (httpx.HTTPError, ValueError, OSError):
        return []


def _from_tags(client: httpx.Client, native: str) -> list[str]:
    try:
        response = client.get(f"{native}/api/tags")
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError, OSError):
        return []
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return []
    names: list[str] = []
    for item in models:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("model") or "").strip()
        if name and not _is_embedding(name, item):
            names.append(name)
    return names


def _from_openai_models(client: httpx.Client, chat_url: str) -> list[str]:
    try:
        response = client.get(f"{chat_url}/models")
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError, OSError):
        return []
    return openai_compatible_model_ids(payload)


def openai_compatible_model_ids(payload: object) -> list[str]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return []
    names: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "").strip()
        if model_id and not _is_embedding(model_id, item):
            names.append(model_id)
    return names


def _is_embedding(name: str, item: Mapping[str, Any] | None = None) -> bool:
    haystacks = [name]
    if item:
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        haystacks.append(str(details.get("family") or ""))
        haystacks.append(str(item.get("owned_by") or ""))
    return any("embed" in value.lower() for value in haystacks if value)
