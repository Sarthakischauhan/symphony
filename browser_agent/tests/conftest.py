"""Every browser test runs offline: no provider key leaks in from the shell."""

from __future__ import annotations

import pytest

KEYS = (
    "AI_GATEWAY_API_KEY",
    "VERCEL_AI_GATEWAY_API_KEY",
    "AI_GATEWAY_BASE_URL",
    "TYPESAFE_API_KEY",
    "TYPESAFE_BASE_URL",
    "OPENROUTER_API_KEY",
    "OPENROUTER_DECISIONS_URL",
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
