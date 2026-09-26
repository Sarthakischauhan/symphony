"""Which Jev endpoint the environment selects. No network."""

from __future__ import annotations

import pytest

from browser_agent.fixture_policy import FixturePolicy
from browser_agent.jev_answers import DecisionError
from browser_agent.jev_credentials import OPENROUTER_URL, TYPESAFE_URL, resolve_jev_endpoint
from browser_agent.jev_policy import JevPolicy, build_policy


def test_no_keys_means_no_endpoint_and_the_fixture_in_auto() -> None:
    assert resolve_jev_endpoint() is None
    assert isinstance(build_policy("auto"), FixturePolicy)
    with pytest.raises(DecisionError):
        build_policy("jev")


def test_vercel_wins_then_typesafe_then_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    assert resolve_jev_endpoint() == ("openrouter", "or-key", "~typesafe/jev-latest", OPENROUTER_URL)
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-key")
    assert resolve_jev_endpoint() == ("typesafe", "ts-key", "jev-latest", TYPESAFE_URL)
    monkeypatch.setenv("VERCEL_AI_GATEWAY_API_KEY", "gw-key")
    endpoint = resolve_jev_endpoint()
    assert endpoint is not None
    assert (endpoint.provider, endpoint.api_key, endpoint.model) == ("vercel", "gw-key", "typesafe-ai/jev")
    assert endpoint.url == "https://ai-gateway.vercel.sh/v4/ai/evaluation-model"
    policy = build_policy("jev")
    assert isinstance(policy, JevPolicy) and policy.provider == "vercel"


def test_explicit_provider_overrides_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "gw-key")
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-key")
    monkeypatch.setenv("SYMPHONY_JEV_PROVIDER", "TypeSafe")
    monkeypatch.setenv("JEV_MODEL", "jev-2")
    monkeypatch.setenv("TYPESAFE_BASE_URL", "https://ts.example/v1/systemone")
    assert resolve_jev_endpoint() == ("typesafe", "ts-key", "jev-2", "https://ts.example/v1/systemone")


def test_explicit_provider_without_its_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "gw-key")
    monkeypatch.setenv("SYMPHONY_JEV_PROVIDER", "typesafe")
    with pytest.raises(DecisionError, match="no API key"):
        resolve_jev_endpoint()
    with pytest.raises(DecisionError):
        build_policy("auto")


def test_unknown_explicit_provider_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "gw-key")
    monkeypatch.setenv("SYMPHONY_JEV_PROVIDER", "bedrock")
    with pytest.raises(DecisionError, match="must be one of"):
        resolve_jev_endpoint()


def test_ai_gateway_base_url_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "gw-key")
    monkeypatch.setenv("AI_GATEWAY_BASE_URL", "https://gateway.internal/v1")
    endpoint = resolve_jev_endpoint()
    assert endpoint is not None
    assert endpoint.url == "https://gateway.internal/v4/ai/evaluation-model"
