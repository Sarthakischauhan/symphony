"""Refresh supported model metadata from the public models.dev catalog."""
from __future__ import annotations

import re

import httpx

from core_ai.models import ModelInfo, ModelPrice, register_model

_URL = "https://models.dev/api.json"
_PROVIDERS = {"openai": ("openai", "responses"), "google": ("gemini", "generate_content"),
              "anthropic": ("anthropic", "messages"), "xai": ("grok", "chat_completions")}
_LEVELS = ("off", "minimal", "low", "medium", "high", "xhigh", "max")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def parse_models(payload: object, providers: set[str]) -> tuple[ModelInfo, ...]:
    """Project text/tool models onto implemented direct-provider APIs."""
    if not isinstance(payload, dict):
        raise ValueError("Invalid models.dev catalog")
    result = []
    for upstream, (provider, api) in _PROVIDERS.items():
        if provider not in providers:
            continue
        data = payload.get(upstream)
        models = data.get("models") if isinstance(data, dict) else None
        if not isinstance(models, dict):
            continue
        for model_id, metadata in models.items():
            if not isinstance(model_id, str) or not _ID.fullmatch(model_id) or not isinstance(metadata, dict):
                continue
            modalities = metadata.get("modalities")
            if not isinstance(modalities, dict) or not isinstance(modalities.get("output"), list):
                continue
            if metadata.get("tool_call") is not True or "text" not in modalities["output"]:
                continue
            if metadata.get("status") in ("deprecated", "retired", "disabled", "decommissioned"):
                continue
            options = metadata.get("reasoning_options")
            values = set()
            if isinstance(options, list):
                for option in options:
                    if isinstance(option, dict) and option.get("type") == "effort" and isinstance(option.get("values"), list):
                        values.update(v for v in option["values"] if isinstance(v, str))
            levels = tuple((level, "none" if level == "off" and "none" in values else level if level in values else None) for level in _LEVELS) if values.intersection((*_LEVELS, "none")) else ()
            limits = metadata.get("limit")
            context = limits.get("context") if isinstance(limits, dict) else None
            if not isinstance(context, int) or isinstance(context, bool) or context <= 0:
                context = None
            cost = metadata.get("cost")
            price = None
            if isinstance(cost, dict):
                def rate(key: str) -> float | None:
                    value = cost.get(key)
                    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value < 1e9 else None
                incoming, outgoing = rate("input"), rate("output")
                if incoming is not None and outgoing is not None:
                    price = ModelPrice(incoming, outgoing, rate("cache_read"), rate("cache_write"))
            model_api = "chat_completions" if provider == "openai" and model_id.startswith(("o1", "o3", "o4")) else api
            result.append(ModelInfo(id=model_id, provider=provider, api=model_api, reasoning=metadata.get("reasoning") is True, thinking_level_map=levels, context_limit=context, price=price))
    return tuple(result)


async def refresh_models(providers: tuple[str, ...]) -> int:
    """Fetch once on demand; retain the shipped catalog on failure or empty data."""
    async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
        response = await client.get(_URL, headers={"Accept": "application/json"})
        response.raise_for_status()
        models = parse_models(response.json(), set(providers))
    if not models:
        raise ValueError("models.dev returned no compatible models")
    for model in models:
        register_model(model)
    return len(models)
