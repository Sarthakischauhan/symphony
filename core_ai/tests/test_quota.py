import asyncio

import httpx
import pytest

from core_ai.oauth.types import OAuthToken
from core_ai.quota import QuotaService, parse_anthropic, parse_openai


def test_openai_parses_single_and_extra_windows():
    windows = parse_openai({"rate_limit": {"primary_window": {"used_percent": 25, "limit_window_seconds": 604800, "reset_at": 1800000000}}, "additional_rate_limits": [{"limit_name": "Spark", "rate_limit": {"primary_window": {"used_percent": 10}}}]})
    assert [(w.label, w.used_percent) for w in windows] == [("Codex · 7 day", 25), ("Spark · Primary", 10)]
    assert windows[0].resets_at is not None


def test_anthropic_parses_partial_and_malformed_windows():
    windows = parse_anthropic({"five_hour": None, "seven_day": {"utilization": 45, "resets_at": "2026-11-01T12:00:00Z"}, "bad": {"utilization": "20"}, "extra_usage": {"is_enabled": False, "utilization": 0}})
    assert len(windows) == 1
    assert windows[0].label == "Seven Day"
    assert windows[0].resets_at is not None
    assert parse_anthropic([]) == ()
    assert parse_openai({"rate_limit": {"primary_window": {"used_percent": float("nan")}}}) == ()


@pytest.mark.parametrize("status,payload,expected", [(200, {"five_hour": {"utilization": 22}}, ""), (401, {}, "Login rejected"), (200, [], "Usage unavailable")])
def test_fetch_and_cache(monkeypatch, status, payload, expected):
    token = OAuthToken(access_token="secret")
    monkeypatch.setattr("core_ai.quota.load_token", lambda _: token)
    monkeypatch.setattr("core_ai.quota.load_valid_token", lambda _: token)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["authorization"] == "Bearer secret"
        assert request.headers["anthropic-beta"]
        return httpx.Response(status, json=payload)

    async def run():
        service = QuotaService(transport=httpx.MockTransport(handler))
        first = await service.get("anthropic")
        assert expected in first.message
        assert await service.get("anthropic") == first
        assert len(calls) == 1
        await service.get("anthropic", refresh=True)
        assert len(calls) == 2

    asyncio.run(run())


def test_api_key_usage_and_unsupported_providers(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-secret")
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "vercel-secret")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-secret")
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.host == "openrouter.ai":
            assert request.headers["authorization"] == "Bearer or-secret"
            return httpx.Response(200, json={"data": {"usage": 1.5, "usage_daily": 0.25, "usage_weekly": 1, "usage_monthly": 1.5}})
        if request.url.host == "ai-gateway.vercel.sh":
            assert request.headers["authorization"] == "Bearer vercel-secret"
            return httpx.Response(200, json={"balance": "95.50", "total_used": "4.50"})
        raise AssertionError(request.url)

    async def run():
        service = QuotaService(transport=httpx.MockTransport(handler))
        openrouter = await service.get("openrouter")
        vercel = await service.get("vercel")
        gemini = await service.get("gemini")
        assert [(item.label, item.used_percent) for item in openrouter.windows] == [("Today", 0.25), ("This week", 1), ("This month", 1.5), ("Total", 1.5)]
        assert [(item.label, item.used_percent) for item in vercel.windows] == [("Balance", 95.5), ("Total used", 4.5)]
        assert "dashboard" in gemini.message.lower()
        assert not any(request.url.host == "generativelanguage.googleapis.com" for request in calls)
        assert await service.get("ollama")
        assert "unavailable" in (await service.get("local")).message.lower()

    asyncio.run(run())


def test_missing_and_expired_credentials(monkeypatch):
    monkeypatch.setattr("core_ai.quota.load_token", lambda _: None)
    async def run():
        service = QuotaService()
        assert "subscription login" in (await service.get("openai")).message
        assert "dashboard" in (await service.get("grok")).message.lower()
        monkeypatch.setattr("core_ai.quota.load_token", lambda _: OAuthToken(access_token="expired"))
        monkeypatch.setattr("core_ai.quota.load_valid_token", lambda _: None)
        assert "expired" in (await service.get("openai")).message
    asyncio.run(run())
