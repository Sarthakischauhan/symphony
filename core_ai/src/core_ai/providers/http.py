import asyncio
import json
import ssl
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, AsyncGenerator, Callable, Dict, Optional

import httpcore
import httpx

from core_ai.types import StreamEvent


HARD_ERROR_MAX_RETRIES = 3

_NON_RETRYABLE_STREAM_ERROR_CODES = {
    "authentication_error",
    "billing_error",
    "billing_hard_limit_reached",
    "content_policy_violation",
    "context_length_exceeded",
    "failed_precondition",
    "insufficient_quota",
    "invalid_argument",
    "invalid_prompt",
    "invalid_request_error",
    "not_found",
    "not_found_error",
    "permission_denied",
    "permission_error",
    "request_too_large",
    "unauthenticated",
}

_SSL_MAC_MARKERS = (
    "bad record mac",
    "bad_record_mac",
    "decryption failed or bad record mac",
    "mac verify failure",
    "sslv3 alert bad record mac",
)

_RETRYABLE_HTTP_STATUSES = {408, 409, 429}


class ConnectionPool(httpcore.AsyncConnectionPool):
    """httpcore's HTTP/1.1 pool, giving each idle connection to one request.

    httpcore 1.0.9 hands an idle connection to every queued request, and keeps
    handing it out until the winner starts sending. The losers raise
    ``ConnectionNotAvailable`` and retry on the next idle connection instead
    of opening one, so a burst of concurrent streams on a shared client runs
    over the few connections left idle by the last burst, a few at a time.
    It also evicts idle connections whenever the whole pool, not the idle
    part, is over ``max_keepalive_connections``. Upstream: encode/httpcore#1035.
    """

    def _assign_requests_to_connections(self) -> list[httpcore.AsyncConnectionInterface]:
        closing: list[httpcore.AsyncConnectionInterface] = []
        reserved = {request.connection for request in self._requests if request.connection is not None}
        idle = sum(1 for connection in self._connections if connection.is_idle())

        for connection in list(self._connections):
            if connection.is_closed():
                self._connections.remove(connection)
            elif connection in reserved:
                continue
            elif connection.has_expired():
                self._connections.remove(connection)
                closing.append(connection)
            elif connection.is_idle() and idle > self._max_keepalive_connections:
                self._connections.remove(connection)
                closing.append(connection)
                idle -= 1

        available = [
            connection
            for connection in self._connections
            if connection.is_available() and connection not in reserved
        ]
        for pool_request in [request for request in self._requests if request.is_queued()]:
            origin = pool_request.request.url.origin
            connection = next(
                (candidate for candidate in available if candidate.can_handle_request(origin)),
                None,
            )
            if connection is not None:
                available.remove(connection)
            elif len(self._connections) < self._max_connections:
                connection = self.create_connection(origin)
                self._connections.append(connection)
            elif available:
                # Full pool: replace an idle connection to another origin.
                stale = available.pop(0)
                self._connections.remove(stale)
                closing.append(stale)
                connection = self.create_connection(origin)
                self._connections.append(connection)
            else:
                continue
            pool_request.assign_to_connection(connection)
        return closing


class PooledTransport(httpx.AsyncHTTPTransport):
    """httpx's default HTTP/1.1 transport over `ConnectionPool`.

    Every pooled connection may stay idle (httpx keeps 20 of 100) until the
    5 s keep-alive expiry. A burst of concurrent streams that needed N
    connections then finds them all warm on the next turn, instead of 80 new
    TLS handshakes competing with 20 reused streams for the event loop.
    """

    def __init__(self, limits: httpx.Limits = httpx.Limits(max_connections=100, max_keepalive_connections=100)) -> None:
        # AsyncHTTPTransport's only state is its pool; build ours instead of
        # letting the base build, and pay the SSL context for, httpcore's.
        self._pool = ConnectionPool(
            ssl_context=httpx.create_ssl_context(),
            max_connections=limits.max_connections,
            max_keepalive_connections=limits.max_keepalive_connections,
            keepalive_expiry=limits.keepalive_expiry,
        )


def is_retryable_http_status(status: int) -> bool:
    """True for statuses `stream_with_retries` will retry."""
    return status in _RETRYABLE_HTTP_STATUSES or status >= 500


class RetryableStreamError(RuntimeError):
    """A provider-reported stream failure that is safe to request again."""

    def __init__(
        self,
        message: str,
        *,
        retry_after: Optional[float] = None,
        reason: str = "stream_error",
    ) -> None:
        super().__init__(message)
        self.retry_after = retry_after
        self.reason = reason


def _exception_chain(exc: BaseException) -> tuple[BaseException, ...]:
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: Optional[BaseException] = exc
    while current is not None and id(current) not in seen:
        chain.append(current)
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return tuple(chain)


def is_ssl_mac_error(exc: BaseException) -> bool:
    """True when the error (or its cause) is an SSL MAC / bad-record failure."""
    for item in _exception_chain(exc):
        message = str(item).lower()
        if any(marker in message for marker in _SSL_MAC_MARKERS):
            return True
        if isinstance(item, ssl.SSLError) and "mac" in message:
            return True
    return False


def _http_status(exc: BaseException) -> Optional[int]:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code
    return None


def apply_refreshed_credentials(provider: Any, refreshed: Any) -> bool:
    """Install a replacement bearer token on a provider. Same token is a no-op."""
    if not isinstance(refreshed, dict):
        return False
    api_key = str(refreshed.get("api_key") or "")
    current = str(getattr(provider, "api_key", "") or "")
    if not api_key or api_key == current:
        return False
    provider.api_key = api_key
    headers = refreshed.get("extra_headers")
    if isinstance(headers, dict):
        provider.extra_headers = {str(key): str(value) for key, value in headers.items()}
    base_url = refreshed.get("base_url")
    if isinstance(base_url, str) and base_url.strip() and hasattr(provider, "base_url"):
        provider.base_url = base_url.rstrip("/")
    return True


def is_auth_failure(exc: BaseException) -> bool:
    """True when a provider rejected the bearer or API credential itself.

    Transport retries must not treat this as a transient outage. Callers that
    can refresh OAuth credentials use it to renew once and send the request again.
    """
    for item in _exception_chain(exc):
        status = _http_status(item)
        if status in {401, 403}:
            return True
        message = str(item).lower()
        if any(
            marker in message
            for marker in (
                "invalid or expired credentials",
                "invalid api key",
                "invalid token",
                "token expired",
                "no auth context",
            )
        ):
            return True
    return False


def is_retryable(exc: BaseException) -> bool:
    """429, SSL MAC, transport, 5xx, and other hard stream failures can be retried."""
    if is_ssl_mac_error(exc):
        return True
    if any(isinstance(item, ssl.SSLError) for item in _exception_chain(exc)):
        return True
    if isinstance(exc, RetryableStreamError):
        return True
    if isinstance(exc, httpx.TransportError):
        return True
    if is_auth_failure(exc):
        return False
    status = _http_status(exc)
    if status is None:
        return False
    return is_retryable_http_status(status)


def retry_reason_for(exc: BaseException) -> str:
    """Stable reason string surfaced on ``StreamEvent.retry_reason``."""
    if is_ssl_mac_error(exc):
        return "ssl_mac_error"
    if any(isinstance(item, ssl.SSLError) for item in _exception_chain(exc)):
        return "ssl_error"
    if isinstance(exc, RetryableStreamError):
        return exc.reason
    status = _http_status(exc)
    if status == 429:
        return "rate_limit"
    if status is not None and (status >= 500 or status in {408, 409}):
        return "server_error"
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    return "connection_error"


def _raise_stream_error(
    data: Dict[str, Any],
) -> None:
    """Raise a retryable or terminal error from a provider SSE payload."""
    response = data.get("response") or {}
    if not isinstance(response, dict):
        response = {}
    error = data.get("error") or response.get("error") or {}
    if not isinstance(error, dict):
        error = {"message": error}

    code_value = error.get("code") or data.get("code")
    status_value = error.get("status") or data.get("status")
    error_type_value = error.get("type") or data.get("error_type")
    identifiers = {
        str(value).lower()
        for value in (code_value, status_value, error_type_value)
        if value is not None
    }
    message = str(
        error.get("message")
        or data.get("message")
        or response.get("message")
        or "Provider stream error"
    )

    numeric_status: Optional[int] = None
    for value in (code_value, status_value):
        try:
            numeric_status = int(value)
        except (TypeError, ValueError):
            continue
        break

    retryable_status = numeric_status in _RETRYABLE_HTTP_STATUSES or (
        numeric_status is not None and numeric_status >= 500
    )
    terminal_status = (
        numeric_status is not None
        and 400 <= numeric_status < 500
        and not retryable_status
    )
    if terminal_status or identifiers & _NON_RETRYABLE_STREAM_ERROR_CODES:
        raise RuntimeError(message)
    raise RetryableStreamError(message)


def retry_after(response: httpx.Response, attempt: int) -> float:
    """Return the server-requested delay, with exponential fallback."""
    value = response.headers.get("retry-after")
    if value:
        try:
            return max(float(value), 0.0)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                return max(
                    (retry_at - datetime.now(timezone.utc)).total_seconds(),
                    0.0,
                )
            except (TypeError, ValueError, OverflowError):
                pass
    return float(min(2 ** (attempt - 1), 60))


def _retry_delay(exc: BaseException, attempt: int) -> float:
    if isinstance(exc, RetryableStreamError) and exc.retry_after is not None:
        return exc.retry_after
    if isinstance(exc, httpx.HTTPStatusError):
        return retry_after(exc.response, attempt)
    return float(min(2 ** (attempt - 1), 60))


async def stream_with_retries(
    factory: Callable[[], AsyncGenerator[StreamEvent, None]],
    *,
    max_retries: int = HARD_ERROR_MAX_RETRIES,
) -> AsyncGenerator[StreamEvent, None]:
    """Retry 429, SSL MAC, transport, and other hard stream failures.

    Rate limits, SSL MAC errors, and 5xx/connection failures are retried up to
    ``max_retries`` times (three by default) with ``Retry-After`` or capped
    exponential backoff. Terminal 4xx errors are not retried.
    """
    attempt = 0
    while True:
        yielded_output = False
        try:
            async for event in factory():
                if event.type not in {"retry", "done"}:
                    yielded_output = True
                yield event
            return
        except Exception as exc:
            if not is_retryable(exc) or attempt >= max_retries:
                raise
            attempt += 1
            delay = _retry_delay(exc, attempt)
            yield StreamEvent(
                type="retry",
                retry_after=delay,
                retry_attempt=attempt,
                retry_reason=retry_reason_for(exc),
                retry_resets_stream=yielded_output,
            )
            await asyncio.sleep(delay)


async def iter_sse_json(response: httpx.Response) -> AsyncGenerator[Dict[str, Any], None]:
    """Yield JSON SSE data, raising centrally for provider error frames.

    ``[DONE]`` ends the data, but the body is still read to its end. Leaving
    early leaves the chunked terminator unread, and httpcore then closes the
    connection instead of returning it to the pool.
    """
    done = False
    async for line in response.aiter_lines():
        if done:
            continue
        line = line.strip()
        if not line.startswith("data: "):
            continue
        raw = line[6:]
        if raw == "[DONE]":
            done = True
            continue
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            event_type = str(data.get("type") or "").lower()
            nested_response = data.get("response") or {}
            nested_error = (
                nested_response.get("error")
                if isinstance(nested_response, dict)
                else None
            )
            if (
                data.get("error")
                or nested_error
                or event_type == "error"
                or event_type.endswith(".failed")
            ):
                _raise_stream_error(data)
            yield data
