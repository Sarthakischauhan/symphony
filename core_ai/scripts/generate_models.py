#!/usr/bin/env python3
"""Generate the shipped core_ai model catalog.

Live provider APIs are used when the matching key is set. Missing keys keep the
existing generated snapshot (or a curated fallback) so packaging can always
produce `src/core_ai/models/generated.py`.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Callable, Iterable

from dotenv import load_dotenv

OUTPUT = Path(__file__).resolve().parents[1] / "src/core_ai/models/generated.py"

# Load local development credentials when the script is run directly. Explicit
# environment variables still win over values from .env.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

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


def render(catalog: dict[str, Iterable[tuple[str, str]]]) -> str:
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
        for model_id, api in models:
            lines.append(
                f'    ModelInfo(id="{model_id}", provider="{provider}", api="{api}"),'
            )
        lines.extend((")", ""))
    lines.append(f"ALL_MODELS = {' + '.join(tuple_names)}")
    lines.append("")
    return "\n".join(lines)


def collect_catalog(*, strict: bool = False, output: Path = OUTPUT) -> dict[str, list[tuple[str, str]]]:
    existing = read_existing_catalog(output)
    openai_key = os.environ.get("OPENAI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    gemini_key = os.environ.get("GOOGLE_GENERATIVE_AI_API_KEY")

    openai_models = (
        load_provider_models(
            "openai",
            lambda: fetch_openai_models(
                openai_key or "",
                os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            ),
            existing=existing["openai"],
            strict=strict and bool(openai_key),
        )
        if openai_key
        else existing["openai"]
    )
    anthropic_models = (
        load_provider_models(
            "anthropic",
            lambda: fetch_anthropic_models(
                anthropic_key or "",
                os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
            ),
            existing=existing["anthropic"],
            strict=strict and bool(anthropic_key),
        )
        if anthropic_key
        else existing["anthropic"]
    )
    gemini_models = (
        load_provider_models(
            "gemini",
            lambda: fetch_gemini_models(
                gemini_key or "",
                os.environ.get(
                    "GEMINI_BASE_URL",
                    "https://generativelanguage.googleapis.com/v1beta",
                ),
            ),
            existing=existing["gemini"],
            strict=strict and bool(gemini_key),
        )
        if gemini_key
        else existing["gemini"]
    )
    return {
        "openai": openai_models,
        "anthropic": anthropic_models,
        "gemini": gemini_models,
    }


def generate(*, strict: bool = False, output: Path = OUTPUT) -> Path:
    catalog = collect_catalog(strict=strict, output=output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(catalog))
    total = sum(len(models) for models in catalog.values())
    print(f"wrote {total} models to {output}")
    return output


def main() -> None:
    generate(strict=os.environ.get("CORE_AI_GENERATE_STRICT") == "1")


if __name__ == "__main__":
    main()
