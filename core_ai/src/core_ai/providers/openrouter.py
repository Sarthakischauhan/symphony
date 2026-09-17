"""OpenRouter via the OpenAI-compatible Chat Completions API."""

from __future__ import annotations

import os
from typing import Optional

import httpx

from core_ai.models import get_model
from core_ai.providers.ollama import openai_compatible_model_ids
from core_ai.providers.openai import OpenAIProvider, openai_compat_base_url

OPENROUTER_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_DOCS_URL = "https://github.com/Sarthakischauhan/symphony"
DISCOVER_TIMEOUT = 8.0


def _attribution_headers() -> dict[str, str]:
    title = (os.getenv("OPENROUTER_TITLE") or "Symphony").strip() or "Symphony"
    referer = (
        os.getenv("OPENROUTER_HTTP_REFERER") or OPENROUTER_DOCS_URL
    ).strip() or OPENROUTER_DOCS_URL
    return {
        "HTTP-Referer": referer,
        "X-Title": title,
        "X-OpenRouter-Title": title,
    }


class OpenRouterProvider(OpenAIProvider):
    """OpenRouter chat completions, including optional app attribution headers."""

    include_stream_options = True
    max_tokens_field = "max_tokens"

    def __init__(
        self,
        api_key: str,
        base_url: str = OPENROUTER_DEFAULT_BASE_URL,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        extra_headers: Optional[dict[str, str]] = None,
    ):
        headers = _attribution_headers()
        headers.update(extra_headers or {})
        super().__init__(
            api_key=api_key,
            base_url=openrouter_chat_base_url(base_url) or OPENROUTER_DEFAULT_BASE_URL,
            transport=transport,
            extra_headers=headers,
        )

    @staticmethod
    def _uses_chat_completions(model_name: str) -> bool:
        return True

    @staticmethod
    def _is_reasoning_model(model_name: str) -> bool:
        model = get_model("openrouter", model_name)
        return bool(model is not None and model.reasoning)

    async def generate_image(
        self,
        model_name: str,
        prompt: str,
        output_format: str = "png",
    ) -> tuple[bytes, str]:
        del model_name, prompt, output_format
        raise NotImplementedError("OpenRouterProvider does not support image generation")


def openrouter_chat_base_url(value: str = "") -> str:
    return openai_compat_base_url(value, default=OPENROUTER_DEFAULT_BASE_URL)


def discover_openrouter_models(
    base_url: str = OPENROUTER_DEFAULT_BASE_URL,
    *,
    api_key: str,
    timeout: float = DISCOVER_TIMEOUT,
    transport: Optional[httpx.BaseTransport] = None,
) -> list[str]:
    """List OpenRouter model slugs. Never raises; returns [] on failure."""
    chat_url = openrouter_chat_base_url(base_url)
    if not chat_url or not api_key:
        return []
    headers = {
        "Authorization": f"Bearer {api_key}",
        **_attribution_headers(),
    }
    try:
        with httpx.Client(transport=transport, timeout=timeout) as client:
            response = client.get(f"{chat_url}/models", headers=headers)
            response.raise_for_status()
            return openai_compatible_model_ids(response.json())
    except (httpx.HTTPError, ValueError, OSError):
        return []
