from typing import Optional

import httpx

from core_ai.models import get_model
from core_ai.providers.openai import OpenAIProvider


class GrokProvider(OpenAIProvider):
    """xAI Grok via the OpenAI-compatible Chat Completions API."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.x.ai/v1",
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        super().__init__(api_key=api_key, base_url=base_url, transport=transport)

    @staticmethod
    def _uses_chat_completions(model_name: str) -> bool:
        return True

    @staticmethod
    def _is_reasoning_model(model_name: str) -> bool:
        model = get_model("grok", model_name)
        if model is not None:
            return model.reasoning
        return True
