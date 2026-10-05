"""Model catalog frames for the stdio host."""

from __future__ import annotations

from core_ai.registry import ModelRegistry

from coding_agent.protocols.stdio.transport import PROTOCOL_VERSION


def model_catalog(registry: ModelRegistry, request_id: str) -> dict[str, object]:
    import core_ai

    default_model_id = core_ai.default_model_id

    namespaces = registry.namespaces()
    models = [
        {
            "id": info.full_id,
            "label": info.id,
            "provider": info.provider,
            "description": info.provider,
            "context_limit": info.context_limit,
            "reasoning_levels": [level for level, _ in info.thinking_level_map if level != "off"],
        }
        for info in registry.models()
        if info.provider in namespaces
    ]
    default = default_model_id(registry)
    selected = next((item for item in models if item["id"] == default), None)
    if selected is None:
        provider, _, label = default.partition(":")
        selected = {
            "id": default,
            "label": label or default,
            "provider": provider or default,
            "description": "Symphony default",
            "context_limit": None,
            "reasoning_levels": [],
        }
    return {
        "type": "models",
        "request_id": request_id,
        "models": [selected, *[item for item in models if item["id"] != default]],
        "default": default,
        "protocol_version": PROTOCOL_VERSION,
    }


__all__ = ["model_catalog"]
