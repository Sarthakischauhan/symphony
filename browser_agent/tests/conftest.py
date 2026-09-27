"""Every browser test runs offline: no provider key leaks in from the shell."""

from __future__ import annotations

from pathlib import Path

import pytest

from core_ai.providers.catalog import PROVIDERS

KEYS = (
    "AI_GATEWAY_API_KEY",
    "VERCEL_AI_GATEWAY_API_KEY",
    "AI_GATEWAY_BASE_URL",
    "TYPESAFE_API_KEY",
    "TYPESAFE_BASE_URL",
    "OPENROUTER_API_KEY",
    "OPENROUTER_BASE_URL",
    "OPENROUTER_DECISIONS_URL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_BASE_URL",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_BASE_URL",
    "SYMPHONY_MODEL",
    "SYMPHONY_JEV_PROVIDER",
    "JEV_MODEL",
    "XAI_API_KEY",
    "XAI_BASE_URL",
    "SYMPHONY_BROWSER_TEXT_MODEL",
)


@pytest.fixture(autouse=True)
def _no_provider_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)
    # uv run loads ~/.env, which can name keys this list does not.
    for spec in PROVIDERS:
        for name in (spec.env_key, *spec.env_aliases, spec.base_url_env, spec.host_env, spec.enabled_env):
            if name:
                monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(f"SYMPHONY_{spec.id.upper()}_AUTH", raising=False)
    # Path.home().resolve() follows the real home even after HOME is changed,
    # so the OAuth directory has to be pointed away from ~/.symphony/oauth.
    monkeypatch.setenv("HOME", "/nonexistent-symphony-home")
    monkeypatch.setattr(Path, "home", lambda: Path("/nonexistent-symphony-home"))
    monkeypatch.setattr(
        "core_ai.oauth.store.oauth_dir",
        lambda: Path("/nonexistent-symphony-home/.symphony/oauth"),
    )
