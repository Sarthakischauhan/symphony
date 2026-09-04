"""Direct tests for provider stream retry classification."""

from __future__ import annotations

import asyncio
import ssl

import httpx
import pytest

from core_ai.providers.http import (
    HARD_ERROR_MAX_RETRIES,
    RetryableStreamError,
    is_retryable,
    is_ssl_mac_error,
    retry_reason_for,
    stream_with_retries,
)
from core_ai.types import StreamEvent


def _status_error(status: int, *, retry_after: str | None = None) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://example.test/v1/stream")
    headers = {"Retry-After": retry_after} if retry_after is not None else None
    response = httpx.Response(status, request=request, headers=headers)
    return httpx.HTTPStatusError("http error", request=request, response=response)


def test_classifies_429_ssl_mac_and_hard_errors() -> None:
    assert is_retryable(_status_error(429))
    assert retry_reason_for(_status_error(429)) == "rate_limit"

    mac = ssl.SSLError("decryption failed or bad record mac (_ssl.c:2559)")
    assert is_ssl_mac_error(mac)
    assert is_retryable(mac)
    assert retry_reason_for(mac) == "ssl_mac_error"

    wrapped = httpx.ReadError("read failed")
    wrapped.__cause__ = ssl.SSLError("SSLV3_ALERT_BAD_RECORD_MAC")
    assert is_retryable(wrapped)
    assert retry_reason_for(wrapped) == "ssl_mac_error"

    assert is_retryable(_status_error(500))
    assert retry_reason_for(_status_error(500)) == "server_error"
    assert is_retryable(httpx.ConnectError("connection reset"))
    assert not is_retryable(_status_error(400))
    assert not is_retryable(RuntimeError("invalid_request_error"))


def test_stream_retries_429_using_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def no_sleep(_delay: float) -> None:
        return None

    async def factory():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _status_error(429, retry_after="0")
        yield StreamEvent(type="text_delta", delta="ok")
        yield StreamEvent(type="done")

    monkeypatch.setattr("core_ai.providers.http.asyncio.sleep", no_sleep)

    async def collect() -> list[StreamEvent]:
        return [event async for event in stream_with_retries(factory)]

    events = asyncio.run(collect())
    assert calls == 2
    assert [event.type for event in events] == ["retry", "text_delta", "done"]
    assert events[0].retry_reason == "rate_limit"
    assert events[0].retry_after == 0
    assert events[0].retry_attempt == 1


def test_stream_retries_ssl_mac_error(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def no_sleep(_delay: float) -> None:
        return None

    async def factory():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ssl.SSLError("DECRYPTION_FAILED_OR_BAD_RECORD_MAC")
        yield StreamEvent(type="text_delta", delta="recovered")
        yield StreamEvent(type="done")

    monkeypatch.setattr("core_ai.providers.http.asyncio.sleep", no_sleep)

    async def collect() -> list[StreamEvent]:
        return [event async for event in stream_with_retries(factory)]

    events = asyncio.run(collect())
    assert calls == 2
    assert events[0].type == "retry"
    assert events[0].retry_reason == "ssl_mac_error"
    assert events[1].delta == "recovered"


def test_hard_errors_retry_three_times_then_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def no_sleep(_delay: float) -> None:
        return None

    async def factory():
        nonlocal calls
        calls += 1
        raise _status_error(503)
        yield StreamEvent(type="done")  # pragma: no cover

    monkeypatch.setattr("core_ai.providers.http.asyncio.sleep", no_sleep)

    async def collect() -> None:
        async for _event in stream_with_retries(factory):
            pass

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(collect())
    assert HARD_ERROR_MAX_RETRIES == 3
    assert calls == HARD_ERROR_MAX_RETRIES + 1


def test_terminal_4xx_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def factory():
        nonlocal calls
        calls += 1
        raise _status_error(401)
        yield StreamEvent(type="done")  # pragma: no cover

    async def collect() -> None:
        async for _event in stream_with_retries(factory):
            pass

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(collect())
    assert calls == 1


def test_retryable_stream_error_still_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def no_sleep(_delay: float) -> None:
        return None

    async def factory():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RetryableStreamError("interrupted", reason="stream_error")
        yield StreamEvent(type="text_delta", delta="ok")
        yield StreamEvent(type="done")

    monkeypatch.setattr("core_ai.providers.http.asyncio.sleep", no_sleep)

    async def collect() -> list[StreamEvent]:
        return [event async for event in stream_with_retries(factory)]

    events = asyncio.run(collect())
    assert calls == 2
    assert [event.type for event in events] == ["retry", "text_delta", "done"]
    assert events[0].retry_reason == "stream_error"
