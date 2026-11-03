"""Provider-reported subscription usage, independent of local token accounting.

The OpenAI and Anthropic HTTP endpoints are unofficial and may change.
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from core_ai.oauth.anthropic import OAUTH_BETA
from core_ai.oauth.openai_codex import chatgpt_account_id
from core_ai.oauth.store import load_token, load_valid_token
from core_ai.providers.catalog import get_provider, provider_api_key, provider_auth_preference


@dataclass(frozen=True)
class QuotaWindow:
    label: str
    used_percent: float
    resets_at: datetime | None = None


@dataclass(frozen=True)
class QuotaResult:
    provider: str
    windows: tuple[QuotaWindow, ...] = ()
    message: str = ""


def _percent(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) and 0 <= value <= 100 else None


def _date(value: Any) -> datetime | None:
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return datetime.fromtimestamp(value / 1000 if value > 1e11 else value, timezone.utc)
        if isinstance(value, str):
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return result if result.tzinfo else result.replace(tzinfo=timezone.utc)
    except (ValueError, OverflowError, OSError):
        pass
    return None


def _amount(value: Any) -> float | None:
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return None
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None


def parse_openrouter(payload: Any) -> tuple[QuotaWindow, ...]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return ()
    labels = (("usage_daily", "Today"), ("usage_weekly", "This week"), ("usage_monthly", "This month"), ("usage", "Total"))
    return tuple(QuotaWindow(label, amount) for key, label in labels if (amount := _amount(data.get(key))) is not None)


def parse_vercel(payload: Any) -> tuple[QuotaWindow, ...]:
    if not isinstance(payload, dict):
        return ()
    labels = (("balance", "Balance"), ("total_used", "Total used"))
    return tuple(QuotaWindow(label, amount) for key, label in labels if (amount := _amount(payload.get(key))) is not None)


def parse_anthropic(payload: Any) -> tuple[QuotaWindow, ...]:
    if not isinstance(payload, dict):
        return ()
    windows = []
    for name, item in payload.items():
        if not isinstance(item, dict) or (name == "extra_usage" and not item.get("is_enabled")):
            continue
        percent = _percent(item.get("utilization"))
        if percent is not None:
            windows.append(QuotaWindow(name.replace("_", " ").title(), percent, _date(item.get("resets_at"))))
    return tuple(windows)


def parse_openai(payload: Any) -> tuple[QuotaWindow, ...]:
    if not isinstance(payload, dict):
        return ()
    windows: list[QuotaWindow] = []

    def add(pool: Any, prefix: str) -> None:
        if not isinstance(pool, dict):
            return
        nested = pool.get("rate_limit")
        if isinstance(nested, dict):
            pool = nested
        for key in ("primary_window", "secondary_window"):
            item = pool.get(key)
            if not isinstance(item, dict):
                continue
            percent = _percent(item.get("used_percent"))
            if percent is None:
                continue
            seconds = item.get("limit_window_seconds")
            period = "5 hour" if seconds == 18000 else "7 day" if seconds == 604800 else key.replace("_window", "").title()
            reset = _date(item.get("reset_at"))
            if reset is None and isinstance(item.get("reset_after_seconds"), (int, float)):
                reset = _date(time.time() + item["reset_after_seconds"])
            windows.append(QuotaWindow(f"{prefix} · {period}", percent, reset))

    add(payload.get("rate_limit"), "Codex")
    add(payload.get("code_review_rate_limit"), "Code review")
    extra = payload.get("additional_rate_limits")
    if isinstance(extra, list):
        for item in extra:
            if isinstance(item, dict):
                add(item, str(item.get("limit_name") or item.get("title") or item.get("metered_feature") or "Additional"))
    return tuple(windows)


class QuotaService:
    """Fetch quota without blocking the event loop; cache per credential for 60 seconds."""

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport
        self._cache: dict[str, tuple[str, float, QuotaResult]] = {}

    async def _api_key_usage(self, provider: str, key: str, *, refresh: bool) -> QuotaResult:
        fingerprint = hashlib.sha256(key.encode()).hexdigest()
        cached = self._cache.get(provider)
        if not refresh and cached and cached[0] == fingerprint and time.monotonic() - cached[1] < 60:
            return cached[2]
        url = "https://openrouter.ai/api/v1/key" if provider == "openrouter" else "https://ai-gateway.vercel.sh/v1/credits"
        headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=10, follow_redirects=False) as client:
                response = await client.get(url, headers=headers)
            if response.status_code in (401, 403):
                result = QuotaResult(provider, message="API key rejected; update it with /login.")
            else:
                response.raise_for_status()
                windows = parse_openrouter(response.json()) if provider == "openrouter" else parse_vercel(response.json())
                result = QuotaResult(provider, windows, "" if windows else "Usage unavailable in provider response.")
        except (httpx.HTTPError, ValueError):
            result = QuotaResult(provider, message="Unable to fetch provider usage.")
        self._cache[provider] = (fingerprint, time.monotonic(), result)
        return result

    async def get(self, provider: str, *, refresh: bool = False) -> QuotaResult:
        spec = get_provider(provider)
        preference = await asyncio.to_thread(provider_auth_preference, spec)
        key = provider_api_key(spec)
        if provider in {"openrouter", "vercel"} and key:
            return await self._api_key_usage(provider, key, refresh=refresh)
        if provider not in {"openai", "anthropic"} or preference == "key" or (preference == "auto" and key):
            message = "Usage is available in the provider dashboard, not through this credential." if provider in {"gemini", "grok"} else "Usage unavailable for this provider."
            return QuotaResult(provider, message=message)
        try:
            stored = await asyncio.to_thread(load_token, provider)
        except (ValueError, OSError, TypeError):
            stored = None
        if stored is None:
            return QuotaResult(provider, message="Usage unavailable without a subscription login.")
        fingerprint = hashlib.sha256(stored.access_token.encode()).hexdigest()
        cached = self._cache.get(provider)
        if not refresh and cached and cached[0] == fingerprint and time.monotonic() - cached[1] < 60:
            return cached[2]
        try:
            token = await asyncio.to_thread(load_valid_token, provider)
        except (ValueError, OSError, TypeError):
            token = None
        if token is None:
            return QuotaResult(provider, message="Login expired; sign in again with /login.")
        fingerprint = hashlib.sha256(token.access_token.encode()).hexdigest()
        headers = {"Authorization": f"Bearer {token.access_token}", "Accept": "application/json"}
        if provider == "openai":
            url = "https://chatgpt.com/backend-api/wham/usage"
            account = token.account_id or chatgpt_account_id(token.access_token, token.id_token)
            if account:
                headers["ChatGPT-Account-Id"] = account
        else:
            url = "https://api.anthropic.com/api/oauth/usage"
            headers["anthropic-beta"] = OAUTH_BETA
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=10, follow_redirects=False) as client:
                response = await client.get(url, headers=headers)
            if response.status_code in (401, 403):
                result = QuotaResult(provider, message="Login rejected; sign in again with /login.")
            else:
                response.raise_for_status()
                payload = response.json()
                windows = parse_openai(payload) if provider == "openai" else parse_anthropic(payload)
                result = QuotaResult(provider, windows, "" if windows else "Usage unavailable in provider response.")
        except (httpx.HTTPError, ValueError):
            result = QuotaResult(provider, message="Unable to fetch provider usage.")
        self._cache[provider] = (fingerprint, time.monotonic(), result)
        return result


quota_service = QuotaService()
