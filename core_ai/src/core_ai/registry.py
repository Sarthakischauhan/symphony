from typing import Any, AsyncGenerator, Dict, List, Optional

from core_ai.models import ModelInfo, list_models, register_model, unregister_model
from core_ai.providers.base import BaseProvider
from core_ai.types import Message, StreamEvent


class ModelRegistry:
    def __init__(self):
        self._providers: Dict[str, BaseProvider] = {}

    def register(self, namespace: str, provider: BaseProvider):
        self._providers[namespace] = provider

    def register_model(self, model: ModelInfo) -> None:
        register_model(model)

    def unregister_model(self, provider: str, model_id: str) -> None:
        unregister_model(provider, model_id)

    def models(self, provider: str | None = None) -> tuple[ModelInfo, ...]:
        return list_models(provider)

    async def stream(
        self,
        model_id: str,
        messages: List[Message],
        tools: List[Dict[str, Any]] = [],
        max_output_tokens: Optional[int] = None,
    ) -> AsyncGenerator[StreamEvent, None]:

        if ":" not in model_id:
            raise ValueError("model_id must be in format 'provider:model_name'")

        provider_name, model_name = model_id.split(":", 1)

        if provider_name not in self._providers:
            raise KeyError(f"Provider '{provider_name}' not registered.")

        provider = self._providers[provider_name]

        async for event in provider.stream(
            model_name,
            messages,
            tools,
            max_output_tokens=max_output_tokens,
        ):
            yield event
