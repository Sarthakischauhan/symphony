"""Vercel AI Gateway via OpenAI-compatible Chat Completions and evaluations.

The Vercel AI SDK talks to this gateway. Symphony uses the same HTTP surface
rather than embedding the TypeScript SDK:

- language models: ``POST https://ai-gateway.vercel.sh/v1/chat/completions``
- evaluation models (for example ``typesafe-ai/jev``):
  ``POST https://ai-gateway.vercel.sh/v4/ai/evaluation-model``
  (see ``core_ai.providers.vercel_evaluation``)
"""

from __future__ import annotations

from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

import core_ai.providers.vercel_evaluation as _evaluation
from core_ai.models import get_model
from core_ai.providers.http import stream_with_retries
from core_ai.providers.ollama import openai_compatible_model_ids
from core_ai.providers.openai import OpenAIProvider, openai_compat_base_url
from core_ai.types import Message, StreamEvent

EVALUATION_SPEC_VERSION = _evaluation.EVALUATION_SPEC_VERSION
evaluation_model_url = _evaluation.evaluation_model_url
evaluation_request_body = _evaluation.evaluation_request_body
evaluation_request_headers = _evaluation.evaluation_request_headers
format_evaluation_answers = _evaluation.format_evaluation_answers
is_evaluation_model = _evaluation.is_evaluation_model
stream_evaluation_model = _evaluation.stream_evaluation_model

VERCEL_DEFAULT_BASE_URL = "https://ai-gateway.vercel.sh/v1"
VERCEL_DEFAULT_GATEWAY_BASE_URL = "https://ai-gateway.vercel.sh/v4/ai"
DISCOVER_TIMEOUT = 8.0
_NON_LANGUAGE_TYPES = {
    "embedding",
    "embeddings",
    "image",
    "video",
    "audio",
    "reranking",
    "rerank",
}


class VercelProvider(OpenAIProvider):
    """Vercel AI Gateway chat completions and evaluation models."""

    include_stream_options = True
    max_tokens_field = "max_tokens"

    def __init__(
        self,
        api_key: str,
        base_url: str = VERCEL_DEFAULT_BASE_URL,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        extra_headers: Optional[dict[str, str]] = None,
    ):
        super().__init__(
            api_key=api_key,
            base_url=vercel_chat_base_url(base_url) or VERCEL_DEFAULT_BASE_URL,
            transport=transport,
            extra_headers=extra_headers,
        )

    async def stream(
        self,
        model_name: str,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_output_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
        extra_headers: Optional[dict[str, str]] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        if is_evaluation_model(model_name):
            async for event in stream_with_retries(
                lambda: stream_evaluation_model(
                    model_name=model_name,
                    messages=messages,
                    api_key=self.api_key,
                    base_url=self.base_url,
                    tools=tools,
                    reasoning_effort=reasoning_effort,
                    transport=self.transport,
                    extra_headers=self.extra_headers,
                )
            ):
                yield event
            return
        async for event in super().stream(
            model_name,
            messages,
            tools,
            max_output_tokens,
            reasoning_effort,
            extra_headers,
        ):
            yield event

    @staticmethod
    def _uses_chat_completions(model_name: str) -> bool:
        return not is_evaluation_model(model_name)

    @staticmethod
    def _is_reasoning_model(model_name: str) -> bool:
        model = get_model("vercel", model_name)
        return bool(model is not None and model.reasoning)

    async def generate_image(
        self,
        model_name: str,
        prompt: str,
        output_format: str = "png",
    ) -> tuple[bytes, str]:
        del model_name, prompt, output_format
        raise NotImplementedError("VercelProvider does not support image generation")


def vercel_chat_base_url(value: str = "") -> str:
    return openai_compat_base_url(value, default=VERCEL_DEFAULT_BASE_URL)


def vercel_gateway_base_url(value: str = "") -> str:
    """Normalize a host or OpenAI-compat URL to the Gateway protocol ``.../v4/ai`` base."""
    raw = (value or "").strip()
    if raw:
        normalized = raw if "://" in raw else f"http://{raw}"
        normalized = normalized.rstrip("/")
        if normalized.endswith("/v4/ai"):
            return normalized
    chat_url = vercel_chat_base_url(value)
    if chat_url.endswith("/v1"):
        return f"{chat_url[:-3]}/v4/ai"
    return VERCEL_DEFAULT_GATEWAY_BASE_URL


def discover_vercel_models(
    base_url: str = VERCEL_DEFAULT_BASE_URL,
    *,
    api_key: str,
    timeout: float = DISCOVER_TIMEOUT,
    transport: Optional[httpx.BaseTransport] = None,
) -> list[str]:
    """List AI Gateway language and evaluation model slugs. Never raises."""
    chat_url = vercel_chat_base_url(base_url)
    if not chat_url or not api_key:
        return []
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        with httpx.Client(transport=transport, timeout=timeout) as client:
            response = client.get(f"{chat_url}/models", headers=headers)
            response.raise_for_status()
            return vercel_model_ids(response.json())
    except (httpx.HTTPError, ValueError, OSError):
        return []


def vercel_model_ids(payload: object) -> list[str]:
    """Keep language and evaluation models; drop embeddings/media/rerankers."""
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return openai_compatible_model_ids(payload)
    names: list[str] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "").strip()
        if not model_id:
            continue
        model_type = str(item.get("type") or "language").strip().lower()
        if model_type in _NON_LANGUAGE_TYPES:
            continue
        names.append(model_id)
    return names


__all__ = [
    "DISCOVER_TIMEOUT",
    "EVALUATION_SPEC_VERSION",
    "VERCEL_DEFAULT_BASE_URL",
    "VERCEL_DEFAULT_GATEWAY_BASE_URL",
    "VercelProvider",
    "discover_vercel_models",
    "evaluation_model_url",
    "evaluation_request_body",
    "evaluation_request_headers",
    "format_evaluation_answers",
    "is_evaluation_model",
    "vercel_chat_base_url",
    "vercel_gateway_base_url",
    "vercel_model_ids",
]
