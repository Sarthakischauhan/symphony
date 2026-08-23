import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, AsyncGenerator, Dict

import httpx


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


async def iter_sse_json(response: httpx.Response) -> AsyncGenerator[Dict[str, Any], None]:
    """Yield JSON objects from an SSE stream, ignoring comments and parse errors."""
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
            yield data
