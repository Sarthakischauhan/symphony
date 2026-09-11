"""Expose the OpenAI models registered in core_ai."""

from __future__ import annotations

from core_ai.providers.catalog import get_provider
from core_ai.registry import ModelRegistry

from core_server.config import ServerConfig
from core_server.models import ModelRegistryResponse, RegistryModel, RegistryProvider


def is_accepted_model(config: ServerConfig, model_id: str) -> bool:
    """Accept qualified models routed by the registered OpenAI provider."""
    provider, separator, _model = model_id.partition(":")
    if not separator or provider != "openai" or "openai" not in config.registry.namespaces():
        return False
    return not config.supported_models or any(
        model.slug == model_id for model in config.supported_models
    )


def model_registry_response(config: ServerConfig) -> ModelRegistryResponse:
    """Build the public registry response from core_ai's OpenAI catalog."""
    allowlist = {model.slug: model for model in config.supported_models}
    models: list[RegistryModel] = []

    def add(model_id: str, label: str) -> None:
        if model_id in {model.id for model in models}:
            return
        if allowlist and model_id not in allowlist:
            return
        models.append(RegistryModel(id=model_id, label=allowlist.get(model_id, None).label if model_id in allowlist else label))

    for model in config.registry.models("openai"):
        add(model.full_id, model.id)
    add(config.model_id, config.model_id.partition(":")[2] or config.model_id)
    for model in config.supported_models:
        if model.slug.startswith("openai:"):
            add(model.slug, model.label)

    default_model = config.model_id if any(model.id == config.model_id for model in models) else (
        get_provider("openai").default_model if any(model.id == get_provider("openai").default_model for model in models) else models[0].id
    )
    provider = RegistryProvider(
        id="openai",
        label=get_provider("openai").label,
        default_model=default_model,
        models=models,
    )
    return ModelRegistryResponse(default_provider_id="openai", providers=[provider] if models else [])
