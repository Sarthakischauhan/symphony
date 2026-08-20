import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
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
        retry_attempt = 0
        while True:
            try:
                async for event in provider.stream(
                    model_name,
                    messages,
                    tools,
                    max_output_tokens=max_output_tokens,
                ):
                    yield event
                return
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 429:
                    raise
                retry_attempt += 1
                retry_after = self._retry_after(exc.response, retry_attempt)
                yield StreamEvent(
                    type="retry",
                    retry_after=retry_after,
                    retry_attempt=retry_attempt,
                )
                await asyncio.sleep(retry_after)

    @staticmethod
    def _uses_chat_completions(model_name: str) -> bool:
        return model_name.startswith(("o1", "o3", "o4"))

    @staticmethod
    def _retry_after(response: httpx.Response, attempt: int) -> float:
        """Return the server-requested delay, with exponential fallback."""
        value = response.headers.get("retry-after")
        if value:
            try:
                return max(float(value), 0.0)
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(value)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=timezone.utc)
                    return max(
                        (retry_at - datetime.now(timezone.utc)).total_seconds(),
                        0.0,
                    )
                except (TypeError, ValueError, OverflowError):
                    pass
        return float(min(2 ** (attempt - 1), 60))
