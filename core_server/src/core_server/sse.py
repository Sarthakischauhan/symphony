"""Control-plane adapter that turns harness events into SSE frames."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional, Union

from core_harness import ControlCommand
from core_harness.control_plane import NullControlPlane
from core_harness.models import ControlPlaneEvent, ControlPlaneEventType


class SSEControlPlane(NullControlPlane):
    """Bounded SSE event queue with harness inbound-command support."""

    def __init__(self, *, max_queue_size: int = 256) -> None:
        if max_queue_size <= 0:
            raise ValueError("max_queue_size must be positive")
        super().__init__()
        self.queue: asyncio.Queue[Optional[ControlPlaneEvent]] = asyncio.Queue(
            maxsize=max_queue_size
        )
        self._consumer_closed = False
        self._closed = False

    async def emit(
        self,
        event_type: Union[str, ControlPlaneEventType],
        payload: Dict[str, Any],
    ) -> None:
        if self._consumer_closed:
            return
        await self.queue.put(ControlPlaneEvent.typed(event_type, payload))

    async def close(self) -> None:
        if self._closed or self._consumer_closed:
            return
        self._closed = True
        await self.queue.put(None)

    async def disconnect(self, reason: str = "client disconnected") -> None:
        """Stop queueing events and cooperatively cancel the active harness run."""
        if self._consumer_closed:
            return
        self._consumer_closed = True
        await self.send_command(ControlCommand.cancel(reason=reason))
        while not self.queue.empty():
            self.queue.get_nowait()


def encode_sse(event: ControlPlaneEvent) -> str:
    data = json.dumps(event.model_dump(), ensure_ascii=False)
    run_id = event.payload.get("run_id")
    sequence = event.payload.get("seq")
    event_id = (
        f"id: {run_id}:{sequence}\n"
        if run_id is not None and sequence is not None
        else ""
    )
    return f"{event_id}event: {event.event_type}\ndata: {data}\n\n"
