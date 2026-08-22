from collections.abc import Iterable

from core_ai.models.generated import OPENAI_MODELS
from core_ai.models.types import ModelInfo


class ModelCatalog:
    def __init__(self, models: Iterable[ModelInfo] = ()) -> None:
        self._models: dict[tuple[str, str], ModelInfo] = {}
        for model in models:
            self.register(model)

    def register(self, model: ModelInfo) -> None:
        self._models[(model.provider, model.id)] = model

    def unregister(self, provider: str, model_id: str) -> None:
        self._models.pop((provider, model_id), None)

    def get(self, provider: str, model_id: str) -> ModelInfo | None:
        return self._models.get((provider, model_id))

    def list(self, provider: str | None = None) -> tuple[ModelInfo, ...]:
        models = self._models.values()
        if provider is not None:
            models = (model for model in models if model.provider == provider)
        return tuple(sorted(models, key=lambda model: (model.provider, model.id)))


model_catalog = ModelCatalog(OPENAI_MODELS)


def register_model(model: ModelInfo) -> None:
    model_catalog.register(model)


def unregister_model(provider: str, model_id: str) -> None:
    model_catalog.unregister(provider, model_id)


def get_model(provider: str, model_id: str) -> ModelInfo | None:
    return model_catalog.get(provider, model_id)


def list_models(provider: str | None = None) -> tuple[ModelInfo, ...]:
    return model_catalog.list(provider)
