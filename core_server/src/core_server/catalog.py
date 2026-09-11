"""Map the live ``ModelRegistry`` onto the Chat SDK registry DTO."""

from __future__ import annotations

from typing import Iterable, Optional

from core_ai.models import ModelInfo
from core_ai.providers.catalog import get_provider
from core_ai.registry import ModelRegistry

from core_server.config import ServerConfig
from core_server.models import (
    ModelRegistryResponse,
    RegistryModel,
    RegistryProvider,
    SupportedModel,
)


def split_model_id(model_id: str) -> Optional[tuple[str, str]]:
    """Return ``(provider, name)`` for a qualified id, or ``None``."""
    if ":" not in model_id:
        return None
    provider, name = model_id.split(":", 1)
    provider = provider.strip()
    name = name.strip()
    if not provider or not name:
        return None
    return provider, name


def registered_namespaces(registry: ModelRegistry) -> tuple[str, ...]:
    return tuple(registry.namespaces())


def registry_can_run(registry: ModelRegistry, model_id: str) -> bool:
    """Whether ``ModelRegistry.stream`` can route this qualified id."""
    parsed = split_model_id(model_id)
    if parsed is None:
        return False
    provider, _name = parsed
    return provider in registered_namespaces(registry)


def allowlist(config: ServerConfig) -> Optional[dict[str, SupportedModel]]:
    """Explicit ``supported_models`` filter, or ``None`` when unrestricted."""
    if not config.supported_models:
        return None
    return {model.slug: model for model in config.supported_models}


def is_accepted_model(config: ServerConfig, model_id: str) -> bool:
    """True when ``/runs`` may use this id: registry-routable, then allowlist."""
    if not registry_can_run(config.registry, model_id):
        return False
    extra = allowlist(config)
    if extra is None:
        return True
    return model_id in extra


def model_registry_response(config: ServerConfig) -> ModelRegistryResponse:
    """Chat SDK ``RegistryConfig`` built from the live registry and catalog."""
    providers = [
        _registry_provider(config, namespace, models)
        for namespace, models in _advertised_models(config)
    ]
    default_provider_id = _default_provider_id(config, providers)
    return ModelRegistryResponse(
        default_provider_id=default_provider_id,
        providers=providers,
    )


def _advertised_models(config: ServerConfig) -> list[tuple[str, list[RegistryModel]]]:
    extra = allowlist(config)
    grouped: list[tuple[str, list[RegistryModel]]] = []
    for namespace in registered_namespaces(config.registry):
        models = _models_for_namespace(config, namespace, extra)
        if models:
            grouped.append((namespace, models))
    return grouped


def _models_for_namespace(
    config: ServerConfig,
    namespace: str,
    extra: Optional[dict[str, SupportedModel]],
) -> list[RegistryModel]:
    seen: set[str] = set()
    models: list[RegistryModel] = []

    def add(model_id: str, label: str) -> None:
        if extra is not None and model_id not in extra:
            return
        if extra is not None:
            label = extra[model_id].label
        if model_id in seen or not registry_can_run(config.registry, model_id):
            return
        seen.add(model_id)
        models.append(RegistryModel(id=model_id, label=label))

    for info in _catalog_models(config.registry, namespace):
        add(info.full_id, info.id)

    parsed = split_model_id(config.model_id)
    if parsed is not None and parsed[0] == namespace:
        add(config.model_id, parsed[1])

    if extra is not None:
        for slug, meta in extra.items():
            parts = split_model_id(slug)
            if parts is not None and parts[0] == namespace:
                add(slug, meta.label)

    return models


def _catalog_models(registry: ModelRegistry, namespace: str) -> tuple[ModelInfo, ...]:
    return registry.models(namespace)


def _registry_provider(
    config: ServerConfig,
    namespace: str,
    models: list[RegistryModel],
) -> RegistryProvider:
    return RegistryProvider(
        id=namespace,
        label=_provider_label(namespace),
        default_model=_provider_default_model(config, namespace, models),
        models=models,
    )


def _provider_label(namespace: str) -> str:
    try:
        return get_provider(namespace).label
    except KeyError:
        return namespace


def _provider_default_model(
    config: ServerConfig,
    namespace: str,
    models: Iterable[RegistryModel],
) -> str:
    ids = [model.id for model in models]
    parsed = split_model_id(config.model_id)
    if parsed is not None and parsed[0] == namespace and config.model_id in ids:
        return config.model_id
    try:
        catalog_default = get_provider(namespace).default_model
    except KeyError:
        catalog_default = None
    if catalog_default is not None and catalog_default in ids:
        return catalog_default
    return ids[0]


def _default_provider_id(
    config: ServerConfig,
    providers: list[RegistryProvider],
) -> str:
    parsed = split_model_id(config.model_id)
    if parsed is not None:
        provider = parsed[0]
        if any(item.id == provider for item in providers):
            return provider
    if providers:
        return providers[0].id
    if parsed is not None:
        return parsed[0]
    return "openai"
