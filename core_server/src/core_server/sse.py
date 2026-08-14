"""Control-plane adapter that turns harness events into SSE frames."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional, Union

from core_harness.models.control_plane import ControlPlaneEvent, ControlPlaneEventType


class SSEControlPlane:
    """Queue each emitted harness event for an SSE response."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[Optional[ControlPlaneEvent]] = asyncio.Queue()

    async def emit(
        self,
        event_type: Union[str, ControlPlaneEventType],
        payload: Dict[str, Any],
    ) -> None:
        await self.queue.put(ControlPlaneEvent.typed(event_type, payload))

    async def close(self) -> None:
        await self.queue.put(None)


def encode_sse(event: ControlPlaneEvent) -> str:
    data = json.dumps(event.model_dump(), ensure_ascii=False)
    return f"event: {event.event_type}\ndata: {data}\n\n"
