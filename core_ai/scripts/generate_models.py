#!/usr/bin/env python3
"""Generate the shipped core_ai model catalog.

This is a maintainer command, not part of installing the package:

    uv run python scripts/generate_models.py

It downloads the curated models.dev catalog, projects it onto the providers
core_ai implements, and rewrites `src/core_ai/models/generated.py`. Commit
the result. If models.dev is unreachable the existing snapshot (or a small
curated fallback) is kept unless `CORE_AI_GENERATE_STRICT=1` is set.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Callable, Iterable

OUTPUT = Path(__file__).resolve().parents[1] / "src/core_ai/models/generated.py"
MODELS_DEV_URL = "https://models.dev/api.json"
MODELS_DEV_PROVIDERS = {
    "openai": "openai",
    "anthropic": "anthropic",
    "gemini": "google",
    "grok": "xai",
}

# models.dev is already curated for model capability. These are the API
# families implemented by core_ai; unlike provider /models endpoints, the
# upstream catalog does not need credentials.

def models_dev_api(provider: str, model_id: str) -> str:
    if provider == "openai" and model_id.startswith(OPENAI_CHAT_COMPLETIONS_PREFIXES):
        return "chat_completions"
    return {
        "openai": "responses",
        "anthropic": "messages",
        "gemini": "generate_content",
        "grok": "chat_completions",
    }[provider]


def effort_map(options: object) -> tuple[tuple[str, str | None], ...]:
    """Normalize models.dev reasoning_options for the /effort UI."""
    if not isinstance(options, list):
        return ()
    values = {
        value
        for option in options
        if isinstance(option, dict) and option.get("type") == "effort"
        for value in option.get("values", [])
        if isinstance(value, str)
    }
    levels = ("off", "minimal", "low", "medium", "high", "xhigh", "max")
    if not values or not (values.intersection(levels) or "none" in values):
        return ()
    return tuple((level, "none" if level == "off" and "none" in values else
                  level if level in values else None) for level in levels)


def fetch_models_dev_models(url: str = MODELS_DEV_URL) -> dict[str, list[tuple[str, str, bool, tuple[tuple[str, str | None], ...]]]]:
    """Load the curated models.dev catalog and project it to our providers.

    The endpoint is one large JSON object, so filtering happens immediately
    while iterating it. Only text-output models with tool calling support are
    emitted; image, embedding, audio, and other entries never enter our
    generated registry.
    """
    import httpx

    response = httpx.get(
        url,
        headers={"User-Agent": "core-ai-model-catalog/1.0"},
        timeout=30.0,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("models.dev catalog must be a JSON object")

    catalog = {provider: [] for provider in MODELS_DEV_PROVIDERS}
    for provider_data in payload.values():
        if not isinstance(provider_data, dict):
            continue
        upstream_provider = provider_data.get("id")
        provider = next((name for name, upstream in MODELS_DEV_PROVIDERS.items() if upstream == upstream_provider), None)
        models = provider_data.get("models")
        if provider is None or not isinstance(models, dict):
            continue
        for model_id, metadata in models.items():
            if not isinstance(model_id, str) or not isinstance(metadata, dict):
                continue
            modalities = metadata.get("modalities") or {}
            output = modalities.get("output") or []
            is_openai_image = provider == "openai" and model_id.startswith("gpt-image-")
            if not is_openai_image and (metadata.get("tool_call") is not True or "text" not in output):
                continue
            catalog[provider].append((model_id, models_dev_api(provider, model_id), metadata.get("reasoning") is True, effort_map(metadata.get("reasoning_options"))))
    return {provider: sorted(set(models)) for provider, models in catalog.items()}



OPENAI_PREFIXES = ("gpt-", "o1", "o3", "o4")
OPENAI_CHAT_COMPLETIONS_PREFIXES = ("o1", "o3", "o4")
GEMINI_ALLOWED_PREFIXES = ("gemini-2.5-", "gemini-3")
GEMINI_SKIP_TOKENS = ("embedding", "image", "tts", "live", "robotics", "computer")
DEPRECATED_STATUSES = {"deprecated", "decommissioned", "retired", "disabled"}
EXISTING_MODEL_RE = re.compile(
    r'ModelInfo\(id="([^"]+)", provider="([^"]+)", api="([^"]+)"\)'
)

FALLBACK_MODELS: dict[str, tuple[tuple[str, str], ...]] = {
    "openai": (
        ("gpt-4.1", "responses"),
        ("gpt-4.1-mini", "responses"),
        ("gpt-4o-mini", "responses"),
        ("gpt-5.6-luna", "responses"),
        ("o3", "chat_completions"),
    ),
    "anthropic": (
        ("claude-fable-5", "messages"),
        ("claude-haiku-4-5", "messages"),
        ("claude-opus-5", "messages"),
        ("claude-sonnet-5", "messages"),
    ),
    "gemini": (
        ("gemini-3.1-pro-preview", "generate_content"),
        ("gemini-3.5-flash", "generate_content"),
        ("gemini-3.6-flash", "generate_content"),
        ("gemini-3.7-flash", "generate_content"),
    ),
    "grok": (
        ("grok-4.3", "chat_completions"),
        ("grok-4.5", "chat_completions"),
        ("grok-4.6", "chat_completions"),
        ("grok-build-0.1", "chat_completions"),
    ),
}


def _is_deprecated(model: dict) -> bool:
    """Return true only when a provider explicitly marks a model unavailable."""
    if model.get("deprecated") is True:
        return True
    for field in ("status", "lifecycle", "state"):
        value = model.get(field)
        if isinstance(value, str) and value.strip().lower() in DEPRECATED_STATUSES:
            return True
    return False


def openai_api(model_id: str) -> str:
    if model_id.startswith(OPENAI_CHAT_COMPLETIONS_PREFIXES):
        return "chat_completions"
    return "responses"


def fetch_openai_models(api_key: str, base_url: str) -> list[tuple[str, str]]:
    import httpx

    response = httpx.get(
        f"{base_url.rstrip('/')}/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30.0,
    )
    response.raise_for_status()
    data = response.json().get("data", [])
    return sorted(
        (model_id, openai_api(model_id))
        for model in data
        if isinstance(model, dict)
        and not _is_deprecated(model)
        and isinstance((model_id := model.get("id")), str)
        and model_id.startswith(OPENAI_PREFIXES)
    )


def fetch_anthropic_models(api_key: str, base_url: str) -> list[tuple[str, str]]:
    import httpx

    models: list[tuple[str, str]] = []
    after_id: str | None = None
    while True:
        params: dict[str, str | int] = {"limit": 100}
        if after_id:
            params["after_id"] = after_id
        response = httpx.get(
            f"{base_url.rstrip('/')}/v1/models",
            params=params,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            timeout=30.0,
        )
        response.raise_for_status()
        payload = response.json()
        for model in payload.get("data", []):
            if not isinstance(model, dict):
                continue
            if _is_deprecated(model):
                continue
            model_id = model.get("id")
            if isinstance(model_id, str) and model_id.startswith("claude-"):
                models.append((model_id, "messages"))
        if not payload.get("has_more"):
            break
        after_id = payload.get("last_id")
        if not after_id:
            break
    return sorted(set(models))


def _gemini_supported(model: dict) -> bool:
    methods = model.get("supportedGenerationMethods") or []
    return "generateContent" in methods or "streamGenerateContent" in methods


def fetch_gemini_models(api_key: str, base_url: str) -> list[tuple[str, str]]:
    import httpx

    models: list[tuple[str, str]] = []
    page_token: str | None = None
    while True:
        params = {"key": api_key}
        if page_token:
            params["pageToken"] = page_token
        response = httpx.get(
            f"{base_url.rstrip('/')}/models",
            params=params,
            timeout=30.0,
        )
        response.raise_for_status()
        payload = response.json()
        for model in payload.get("models", []):
            if (
                not isinstance(model, dict)
                or _is_deprecated(model)
                or not _gemini_supported(model)
            ):
                continue
            name = model.get("name")
            if not isinstance(name, str):
                continue
            model_id = name.removeprefix("models/")
            lowered = model_id.lower()
            if not model_id.startswith(GEMINI_ALLOWED_PREFIXES):
                continue
            if any(token in lowered for token in GEMINI_SKIP_TOKENS):
                continue
            models.append((model_id, "generate_content"))
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
    return sorted(set(models))


def read_existing_catalog(path: Path = OUTPUT) -> dict[str, list[tuple[str, str]]]:
    found: dict[str, list[tuple[str, str]]] = {
        "openai": [],
        "anthropic": [],
        "gemini": [],
        "grok": [],
    }
    if path.exists():
        for model_id, provider, api in EXISTING_MODEL_RE.findall(path.read_text()):
            if provider in found:
                found[provider].append((model_id, api))
    for provider, models in found.items():
        if not models:
            found[provider] = list(FALLBACK_MODELS[provider])
    return found


def load_provider_models(
    provider: str,
    fetch: Callable[[], list[tuple[str, str]]],
    *,
    existing: list[tuple[str, str]],
    strict: bool,
) -> list[tuple[str, str]]:
    try:
        models = fetch()
        if models:
            return models
        if strict:
            raise RuntimeError(f"{provider} returned no models")
    except Exception:
        if strict:
            raise
    return list(existing)


def render(catalog: dict[str, Iterable[tuple]]) -> str:
    lines = [
        "# Generated by scripts/generate_models.py. Do not edit by hand.",
        "",
        "from core_ai.models.types import ModelInfo",
        "",
    ]
    tuple_names = []
    for provider, models in catalog.items():
        name = f"{provider.upper()}_MODELS"
        tuple_names.append(name)
        lines.append(f"{name} = (")
        for model in models:
            if len(model) == 2:
                model_id, api = model
                reasoning = False
                thinking_level_map = ()
            else:
                model_id, api, reasoning, thinking_level_map = model
            args = [
                f'id="{model_id}"',
                f'provider="{provider}"',
                f'api="{api}"',
            ]
            if reasoning:
                args.append("reasoning=True")
            if thinking_level_map:
                args.append(f"thinking_level_map={thinking_level_map!r}")
            lines.append(f"    ModelInfo({', '.join(args)}),")
        lines.extend((")", ""))
    lines.append(f"ALL_MODELS = {' + '.join(tuple_names)}")
    lines.append("")
    return "\n".join(lines)


def collect_catalog(*, strict: bool = False, output: Path = OUTPUT) -> dict[str, list[tuple[str, str]]]:
    """Build our catalog from the curated models.dev registry.

    Provider credentials are deliberately not required: models.dev is the
    catalog source, while credentials are only needed when a model is used.
    Keeping the checked-in snapshot on failure makes package builds offline
    safe. Set CORE_AI_MODELS_DEV=0 to intentionally skip the network request.
    """
    existing = read_existing_catalog(output)
    if os.environ.get("CORE_AI_MODELS_DEV", "1") == "0":
        return existing

    try:
        catalog = fetch_models_dev_models(
            os.environ.get("MODELS_DEV_URL", MODELS_DEV_URL)
        )
        if not any(catalog.values()):
            raise RuntimeError("models.dev returned no supported models")
        return catalog
    except Exception:
        if strict:
            raise
        return existing


def generate(*, strict: bool = False, output: Path = OUTPUT) -> Path:
    catalog = collect_catalog(strict=strict, output=output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(catalog))
    total = sum(len(models) for models in catalog.values())
    print(f"wrote {total} models to {output}")
    return output


def main() -> None:
    # Local development credentials are only loaded for direct script runs;
    # explicit environment variables still win over values from .env.
    try:
        from dotenv import load_dotenv
    except ImportError:
        pass
    else:
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    generate(strict=os.environ.get("CORE_AI_GENERATE_STRICT") == "1")


if __name__ == "__main__":
    main()
