from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx
from dotenv import load_dotenv

from core_ai.providers.base import BaseProvider
from core_ai.providers.openai_completion import OpenAICompletionProvider
from core_ai.providers.openai_responses import OpenAIResponsesProvider
from core_ai.types import Message, StreamEvent

load_dotenv(override=True)


class OpenAIProvider(BaseProvider):
    """Small switcher between OpenAI's two streaming APIs."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self._completion = OpenAICompletionProvider(api_key, base_url, transport)
        self._responses = OpenAIResponsesProvider(api_key, base_url, transport)

    async def stream(
        self,
        model_name: str,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_output_tokens: Optional[int] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        provider = (
            self._completion
            if self._uses_chat_completions(model_name)
            else self._responses
        )
        async for event in provider.stream(
            model_name,
            messages,
            tools,
            max_output_tokens=max_output_tokens,
        ):
            yield event

    @staticmethod
    def _uses_chat_completions(model_name: str) -> bool:
        return model_name.startswith(("o1", "o3", "o4"))
