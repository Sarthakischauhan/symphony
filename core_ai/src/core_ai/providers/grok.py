from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

from core_ai.models import get_model
from core_ai.providers.openai import OpenAIProvider
from core_ai.types import Message, StreamEvent


class GrokProvider(OpenAIProvider):
    """xAI Grok via the OpenAI-compatible Chat Completions API."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.x.ai/v1",
        transport: Optional[httpx.AsyncBaseTransport] = None,
        extra_headers: Optional[dict[str, str]] = None,
    ):
        super().__init__(
            api_key=api_key,
            base_url=base_url,
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
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        headers = dict(extra_headers or {})
        async for event in super().stream(
            model_name,
            messages,
            tools,
            max_output_tokens,
            reasoning_effort,
            headers,
        ):
            yield event

    @staticmethod
    def _uses_chat_completions(model_name: str) -> bool:
        return True

    @staticmethod
    def _is_reasoning_model(model_name: str) -> bool:
        model = get_model("grok", model_name)
        if model is not None:
            return model.reasoning
        return True
