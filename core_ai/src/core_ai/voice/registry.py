"""Voice providers by namespace, opened by ``namespace:model`` id, and the voice models served."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Optional

from core_ai.voice.catalog import VOICE_MODELS
from core_ai.voice.session import FrameObserver, VoiceConfig, VoiceSession
from core_ai.voice.types import VoiceModel, VoiceModelSpec


class VoiceProvider(ABC):
    """Opens realtime connections to one provider's voice models."""

    @abstractmethod
    async def open(
        self,
        model_name: str,
        config: VoiceConfig,
        observer: Optional[FrameObserver] = None,
    ) -> VoiceSession:
        """Connect to ``model_name`` and apply ``config``."""


class MissingVoiceContextLimit(ValueError):
    """A voice model has no configured context window."""

    def __init__(self, model_ids: list[str]) -> None:
        self.model_ids = model_ids
        super().__init__(
            "no context_limit configured for voice model(s) "
            + ", ".join(model_ids)
            + "; xAI does not publish one, so the host must set it per model"
        )


class VoiceRegistry:
    """Voice providers by namespace and the voice models they serve (``specs``, by default
    ``VOICE_MODELS``), apart from the text ``ModelRegistry``.

    ``context_limits`` (tokens, by ``namespace:model`` id) is required for every model: xAI
    documents no context window for its realtime models (the models list,
    https://docs.x.ai/developers/models, gives text models a ``maxPromptLength`` and voice
    models none), so the host configures one rather than this package guessing.
    """

    def __init__(self, context_limits: Mapping[str, int], specs: tuple[VoiceModelSpec, ...] = VOICE_MODELS) -> None:
        missing = [spec.full_id for spec in specs if spec.full_id not in context_limits]
        if missing:
            raise MissingVoiceContextLimit(missing)
        self._models = tuple(VoiceModel(spec, context_limits[spec.full_id]) for spec in specs)
        self._providers: dict[str, VoiceProvider] = {}

    def register(self, namespace: str, provider: VoiceProvider) -> None:
        self._providers[namespace] = provider

    def unregister(self, namespace: str) -> None:
        self._providers.pop(namespace, None)

    def namespaces(self) -> tuple[str, ...]:
        return tuple(self._providers)

    def models(self) -> tuple[VoiceModel, ...]:
        """Every voice model, registered provider or not."""
        return self._models

    def get(self, model_id: str) -> VoiceModel | None:
        return next((model for model in self._models if model.full_id == model_id), None)

    async def open(
        self,
        model_id: str,
        config: VoiceConfig,
        observer: Optional[FrameObserver] = None,
    ) -> VoiceSession:
        if ":" not in model_id:
            raise ValueError("model_id must be in format 'provider:model_name'")
        namespace, model_name = model_id.split(":", 1)
        if namespace not in self._providers:
            raise KeyError(f"Voice provider '{namespace}' not registered.")
        return await self._providers[namespace].open(model_name, config, observer)
