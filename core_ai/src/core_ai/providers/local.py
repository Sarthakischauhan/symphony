"""Generic local OpenAI-compatible server (LM Studio, vLLM, llama.cpp, SGLang).

Same chat-completions path as Ollama / pi-ai custom providers: dummy key,
no `stream_options`, `max_tokens`. Opt-in is `LOCAL_BASE_URL` — never a
localhost probe.
"""

from __future__ import annotations

from typing import Optional

import httpx

from core_ai.providers.ollama import openai_compatible_model_ids
from core_ai.providers.openai import OpenAIProvider, openai_compat_base_url

LOCAL_DUMMY_KEY = "local"
LOCAL_DEFAULT_BASE_URL = "http://127.0.0.1:1234/v1"
DISCOVER_TIMEOUT = 2.0


class LocalProvider(OpenAIProvider):
    """Any OpenAI-compatible local inference server."""

    include_stream_options = False
    max_tokens_field = "max_tokens"

    def __init__(
        self,
        api_key: str = LOCAL_DUMMY_KEY,
        base_url: str = LOCAL_DEFAULT_BASE_URL,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        super().__init__(
            api_key=api_key or LOCAL_DUMMY_KEY,
            base_url=local_chat_base_url(base_url) or LOCAL_DEFAULT_BASE_URL,
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
        raise NotImplementedError("LocalProvider does not support image generation")


def local_chat_base_url(value: str = "") -> str:
    return openai_compat_base_url(value)


def discover_local_models(
    base_url: str,
    *,
    api_key: str = LOCAL_DUMMY_KEY,
    timeout: float = DISCOVER_TIMEOUT,
    transport: Optional[httpx.BaseTransport] = None,
) -> list[str]:
    """List models from `GET {base}/models`. Never raises; returns [] on failure."""
    chat_url = local_chat_base_url(base_url)
    if not chat_url:
        return []
    headers = {"Authorization": f"Bearer {api_key or LOCAL_DUMMY_KEY}"}
    try:
        with httpx.Client(transport=transport, timeout=timeout) as client:
            response = client.get(f"{chat_url}/models", headers=headers)
            response.raise_for_status()
            return openai_compatible_model_ids(response.json())
    except (httpx.HTTPError, ValueError, OSError):
        return []
