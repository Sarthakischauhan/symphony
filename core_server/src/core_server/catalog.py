"""Map the live core_ai registry to the public model-picker protocol."""

from __future__ import annotations

from core_ai.providers.catalog import get_provider

from core_server.config import ServerConfig
from core_server.models import (
    ModelRegistryResponse,
    RegistryModel,
    RegistryProvider,
    ThinkingLevel,
)


def is_accepted_model(config: ServerConfig, model_id: str) -> bool:
    """Accept a qualified model routed by one of the registered providers."""
    provider, separator, _model = model_id.partition(":")
    if not separator or provider not in config.registry.namespaces():
        return False
    return not config.supported_models or any(
        model.slug == model_id for model in config.supported_models
    )


def model_registry_response(config: ServerConfig) -> ModelRegistryResponse:
    """Build the provider-local model-picker response from core_ai's registry."""
    allowlist = {model.slug: model for model in config.supported_models}
    providers: list[RegistryProvider] = []

    for provider_id in config.registry.namespaces():
        try:
            spec = get_provider(provider_id)
            provider_label = spec.label
            provider_default = spec.default_model
        except KeyError:
            provider_label = provider_id.replace("-", " ").title()
            provider_default = ""
        models: list[RegistryModel] = []
        seen: set[str] = set()

        def add(
            model_id: str,
            label: str,
            thinking_levels: tuple[ThinkingLevel, ...] = (),
        ) -> None:
            qualified_id = f"{provider_id}:{model_id}"
            if model_id in seen or (allowlist and qualified_id not in allowlist):
                return
            seen.add(model_id)
            models.append(
                RegistryModel(
                    id=qualified_id,
                    label=allowlist[qualified_id].label if qualified_id in allowlist else label,
                    thinking_levels=list(thinking_levels),
                )
            )

        for model in config.registry.models(provider_id):
            add(
                model.id,
                _model_label(model.id),
                tuple(
                    "none" if level == "off" else level
                    for level, provider_value in model.thinking_level_map
                    if provider_value is not None
                ),
            )

        configured_provider, configured_separator, configured_model = (
            config.model_id.partition(":")
        )
        if configured_provider == provider_id and configured_separator:
            add(configured_model, _model_label(configured_model))

        for model in config.supported_models:
            supported_provider, supported_separator, supported_model = (
                model.slug.partition(":")
            )
            if supported_provider == provider_id and supported_separator:
                add(supported_model, model.label)

        default_model = provider_default
        if (
            configured_provider == provider_id
            and configured_separator
            and configured_model in seen
        ):
            default_model = config.model_id
        elif default_model not in {model.id for model in models} and models:
            default_model = models[0].id

        if models:
            providers.append(
                RegistryProvider(
                    id=provider_id,
                    label=provider_label,
                    logo=_provider_logo(provider_id),
                    default_model=default_model,
                    models=models,
                )
            )

    default_provider_id = config.model_id.partition(":")[0]
    if default_provider_id not in {provider.id for provider in providers}:
        default_provider_id = providers[0].id if providers else ""
    return ModelRegistryResponse(default_provider_id=default_provider_id, providers=providers)


_MODEL_LABELS = {
    "gpt-4.1": "GPT-4.1",
    "claude-3-7-sonnet-20250219": "Claude 3.7 Sonnet",
}


def _model_label(model_id: str) -> str:
    if model_id in _MODEL_LABELS:
        return _MODEL_LABELS[model_id]
    words = model_id.replace("-", " ").replace("_", " ").split()
    return " ".join(
        word.upper()
        if word.lower() in {"gpt", "o1", "o3", "o4"}
        else word.capitalize()
        for word in words
    )


def _provider_logo(provider_id: str) -> str:
    logo_id = {"gemini": "google", "grok": "xai"}.get(provider_id, provider_id)
    return f"https://models.dev/logos/{logo_id}.svg"
