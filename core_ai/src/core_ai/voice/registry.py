"""Voice providers by namespace, opened by ``namespace:model`` id against a voice catalog."""

from abc import ABC, abstractmethod
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


class VoiceRegistry:
    """The voice counterpart of ``ModelRegistry``; its models come from ``catalog``, not the
    default text catalog."""

    def __init__(self, catalog: ModelCatalog = voice_catalog) -> None:
        self.catalog = catalog
        self._providers: dict[str, VoiceProvider] = {}

    def register(self, namespace: str, provider: VoiceProvider) -> None:
        self._providers[namespace] = provider

    def unregister(self, namespace: str) -> None:
        self._providers.pop(namespace, None)

    def namespaces(self) -> tuple[str, ...]:
        return tuple(self._providers)

    def models(self) -> tuple[ModelInfo, ...]:
        """Catalog models whose provider namespace is registered."""
        return tuple(m for m in self.catalog.list() if m.provider in self._providers)

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
