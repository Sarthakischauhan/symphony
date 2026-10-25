from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

from core_ai.models import get_model
from core_ai.providers.grok_voice import GrokVoiceSession
from core_ai.providers.openai import OpenAIProvider
from core_ai.types import Message, StreamEvent
from core_ai.voice.session import FrameObserver, VoiceConfig, VoiceSession


GROK_IMAGE_MODEL = "grok-imagine-image-2.0"


class GrokProvider(OpenAIProvider):
    """xAI Grok via the OpenAI-compatible Chat Completions API."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.x.ai/v1",
        transport: Optional[httpx.AsyncBaseTransport] = None,
        extra_headers: Optional[dict[str, str]] = None,
        credential_refresher: Optional[Any] = None,
    ):
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            transport=transport,
            extra_headers=extra_headers,
            credential_refresher=credential_refresher,
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

    def image_request(self, model_name: str, output_format: str) -> tuple[Dict[str, Any], str]:
        # xAI's Images API takes no size or output format and always returns JPEG.
        del output_format
        model = model_name if model_name.startswith("grok-imagine") else GROK_IMAGE_MODEL
        return {"model": model, "n": 1, "response_format": "b64_json"}, "image/jpeg"

    async def open_voice(
        self,
        model_name: str,
        config: VoiceConfig,
        observer: Optional[FrameObserver] = None,
    ) -> VoiceSession:
        return await GrokVoiceSession.open(
            self.realtime_url, self.api_key, model_name, config, observer
        )

    @property
    def realtime_url(self) -> str:
        """``wss://…/realtime`` on the same host as the REST base URL."""
        scheme, rest = self.base_url.split("://", 1)
        return f"{'wss' if scheme == 'https' else 'ws'}://{rest}/realtime"

    @staticmethod
    def _uses_chat_completions(model_name: str) -> bool:
        return True

    @staticmethod
    def _is_reasoning_model(model_name: str) -> bool:
        model = get_model("grok", model_name)
        if model is not None:
            return model.reasoning
        return True
