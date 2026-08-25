import asyncio
import base64
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx
from dotenv import load_dotenv

from core_ai.models import get_model
from core_ai.providers.base import BaseProvider
from core_ai.providers.http import retry_after
from core_ai.providers.openai_completion import OpenAICompletionProvider
from core_ai.providers.openai_responses import OpenAIResponsesProvider
from core_ai.types import Message, StreamEvent

load_dotenv(override=True)

_FORMAT_MEDIA = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}


class OpenAIProvider(BaseProvider):
    """Small switcher between OpenAI's two streaming APIs."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.transport = transport
        self._completion = OpenAICompletionProvider(api_key, self.base_url, transport)
        self._responses = OpenAIResponsesProvider(api_key, self.base_url, transport)

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
                delay = retry_after(exc.response, retry_attempt)
                yield StreamEvent(
                    type="retry",
                    retry_after=delay,
                    retry_attempt=retry_attempt,
                )
                await asyncio.sleep(delay)

    async def generate_image(
        self,
        model_name: str,
        prompt: str,
        output_format: str = "png",
    ) -> tuple[bytes, str]:
        model = (
            model_name
            if model_name.startswith(("gpt-image", "dall-e"))
            else "gpt-image-1"
        )
        body: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "n": 1,
            "size": "1024x1024",
        }
        if model.startswith("gpt-image"):
            body["output_format"] = output_format
        else:
            body["response_format"] = "b64_json"
        async with httpx.AsyncClient(transport=self.transport, timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/images/generations",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            if response.status_code >= 400:
                raise RuntimeError(_http_error(response))
            payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not data:
            raise RuntimeError("provider returned no image data")
        item = data[0] if isinstance(data[0], dict) else {}
        encoded = item.get("b64_json")
        media_type = _FORMAT_MEDIA.get(output_format, "image/png")
        if encoded:
            return base64.b64decode(encoded), media_type
        url = str(item.get("url") or "")
        if not url:
            raise RuntimeError("provider returned no image data")
        async with httpx.AsyncClient(transport=self.transport, timeout=120.0) as client:
            downloaded = await client.get(url)
            if downloaded.status_code >= 400:
                raise RuntimeError(_http_error(downloaded))
            return downloaded.content, media_type

    @staticmethod
    def _uses_chat_completions(model_name: str) -> bool:
        model = get_model("openai", model_name)
        if model is not None:
            return model.api == "chat_completions"
        return model_name.startswith(("o1", "o3", "o4"))


def _http_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
        if isinstance(error, str) and error:
            return error
    return (response.text or "").strip() or f"HTTP {response.status_code}"
