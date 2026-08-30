import asyncio
import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, AsyncGenerator, Callable, Dict, Optional

import httpx

from core_ai.types import StreamEvent


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

    retryable_status = numeric_status in {408, 409, 429} or (
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


async def stream_with_retries(
    factory: Callable[[], AsyncGenerator[StreamEvent, None]],
    *,
    max_retries: int = 3,
) -> AsyncGenerator[StreamEvent, None]:
    """Retry transient HTTP, transport, and provider-reported stream failures."""
    attempt = 0
    while True:
        yielded_output = False
        try:
            async for event in factory():
                if event.type not in {"retry", "done"}:
                    yielded_output = True
                yield event
            return
        except (httpx.HTTPStatusError, httpx.TransportError, RetryableStreamError) as exc:
            response = exc.response if isinstance(exc, httpx.HTTPStatusError) else None
            status = response.status_code if response is not None else None
            retryable_status = status in {408, 409, 429} or (
                status is not None and status >= 500
            )
            if isinstance(exc, httpx.HTTPStatusError) and not retryable_status:
                raise
            if attempt >= max_retries:
                raise
            attempt += 1
            if isinstance(exc, RetryableStreamError):
                delay = (
                    exc.retry_after
                    if exc.retry_after is not None
                    else float(min(2 ** (attempt - 1), 60))
                )
                reason = exc.reason
            elif response is not None:
                delay = retry_after(response, attempt)
                reason = "rate_limit" if status == 429 else "server_error"
            else:
                delay = float(min(2 ** (attempt - 1), 60))
                reason = "connection_error"
            yield StreamEvent(
                type="retry",
                retry_after=delay,
                retry_attempt=attempt,
                retry_reason=reason,
                retry_resets_stream=yielded_output,
            )
            await asyncio.sleep(delay)


async def iter_sse_json(response: httpx.Response) -> AsyncGenerator[Dict[str, Any], None]:
    """Yield JSON SSE data, raising centrally for provider error frames."""
    async for line in response.aiter_lines():
        line = line.strip()
        if not line.startswith("data: "):
            continue
        raw = line[6:]
        if raw == "[DONE]":
            break
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
