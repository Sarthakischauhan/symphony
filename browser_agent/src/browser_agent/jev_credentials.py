"""Pick the Jev endpoint from the environment.

Vercel AI Gateway wins when several keys are set, because that is how the
rest of Symphony already calls ``typesafe-ai/jev``. ``SYMPHONY_JEV_PROVIDER``
(``vercel``, ``typesafe``, or ``openrouter``) forces one provider; forcing one
whose key is missing is an error, never a silent switch to another provider.
"""

from __future__ import annotations

import os
from typing import NamedTuple, Optional

from core_ai.providers.catalog import get_provider, provider_api_key
from core_ai.providers.vercel_evaluation import evaluation_model_url

from browser_agent.jev_answers import DecisionError

TYPESAFE_URL = "https://api.typesafe.ai/v1/systemone"
OPENROUTER_URL = "https://openrouter.ai/api/alpha/decisions"
VERCEL_MODEL = "typesafe-ai/jev"
PROVIDERS = ("vercel", "typesafe", "openrouter")


class JevEndpoint(NamedTuple):
    """Where and as whom one Jev request is sent."""

    provider: str
    api_key: str
    model: str
    url: str


def _endpoint(provider: str) -> JevEndpoint:
    model = os.getenv("JEV_MODEL", "").strip()
    if provider == "vercel":
        spec = get_provider("vercel")
        base_url = os.getenv(spec.base_url_env, "").strip() or spec.default_base_url
        url = evaluation_model_url(base_url)
        return JevEndpoint(provider, provider_api_key(spec) or "", model or VERCEL_MODEL, url)
    if provider == "typesafe":
        url = os.getenv("TYPESAFE_BASE_URL", "").strip() or TYPESAFE_URL
        return JevEndpoint(provider, os.getenv("TYPESAFE_API_KEY", "").strip(), model or "jev-latest", url)
    url = os.getenv("OPENROUTER_DECISIONS_URL", "").strip() or OPENROUTER_URL
    key = provider_api_key(get_provider("openrouter")) or ""
    return JevEndpoint(provider, key, model or "~typesafe/jev-latest", url)


def resolve_jev_endpoint() -> Optional[JevEndpoint]:
    """The first provider with a key, or the forced one. None when no key is set at all."""
    explicit = os.getenv("SYMPHONY_JEV_PROVIDER", "").strip().lower()
    if explicit and explicit not in PROVIDERS:
        raise DecisionError(f"SYMPHONY_JEV_PROVIDER must be one of {', '.join(PROVIDERS)}, got {explicit!r}.")
    for provider in (explicit,) if explicit else PROVIDERS:
        endpoint = _endpoint(provider)
        if endpoint.api_key:
            return endpoint
    if explicit:
        raise DecisionError(f"SYMPHONY_JEV_PROVIDER={explicit} is set but that provider has no API key.")
    return None


__all__ = ["JevEndpoint", "resolve_jev_endpoint"]
