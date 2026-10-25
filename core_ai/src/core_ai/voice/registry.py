"""Voice providers by namespace, opened by ``namespace:model`` id against a voice catalog."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Optional

from core_ai.models.registry import ModelCatalog
from core_ai.models.types import ModelInfo
from core_ai.voice.catalog import voice_catalog
from core_ai.voice.session import FrameObserver, VoiceConfig, VoiceSession


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
    """A voice model in the catalog has no configured context window."""

    def __init__(self, model_ids: list[str]) -> None:
        self.model_ids = model_ids
        super().__init__(
            "no context_limit configured for voice model(s) "
            + ", ".join(model_ids)
            + "; xAI does not publish one, so the host must set it per model"
        )


class VoiceRegistry:
    """The voice counterpart of ``ModelRegistry``; its models come from ``catalog``, not the
    default text catalog.

    ``context_limits`` (tokens, by ``namespace:model`` id) is required for every catalog model:
    xAI documents no context window for its realtime models (the models list,
    https://docs.x.ai/developers/models, gives text models a ``maxPromptLength`` and voice
    models none), so the host configures one rather than this package guessing.
    """

    def __init__(self, context_limits: Mapping[str, int], catalog: ModelCatalog = voice_catalog) -> None:
        missing = [model.full_id for model in catalog.list() if model.full_id not in context_limits]
        if missing:
            raise MissingVoiceContextLimit(missing)
        self.catalog = catalog
        self._context_limits = {model.full_id: context_limits[model.full_id] for model in catalog.list()}
        self._providers: dict[str, VoiceProvider] = {}

    def context_limits(self) -> dict[str, int]:
        """The configured context window of every catalog model, by full id."""
        return dict(self._context_limits)

    def register(self, namespace: str, provider: VoiceProvider) -> None:
        self._providers[namespace] = provider

    def unregister(self, namespace: str) -> None:
        self._providers.pop(namespace, None)

    def namespaces(self) -> tuple[str, ...]:
        return tuple(self._providers)

    def models(self) -> tuple[ModelInfo, ...]:
        """Every voice model in the catalog, registered provider or not (as ``ModelRegistry``)."""
        return self.catalog.list()

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
