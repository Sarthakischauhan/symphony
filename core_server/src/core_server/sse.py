"""Event-sink adapter that turns harness events into SSE frames."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional, Sequence, Union

from core_harness import ControlPlaneEvent, ControlPlaneEventType, EventSink


class SSEEventSink(EventSink):
    """Bounded SSE event queue. Cancel the run task on disconnect; this
    object only stops queueing events."""

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
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        if self._consumer_closed:
            return
        await self.queue.put(ControlPlaneEvent.typed(event_type, payload or {}))

    async def request_user_input(
        self,
        *,
        question: str,
        choices: Sequence[str] = (),
        default: str = "",
        kind: str = "question",
        metadata: Optional[Dict[str, Any]] = None,
        emit: Optional[
            Callable[[str, Dict[str, Any]], Awaitable[None]]
        ] = None,
    ) -> str:
        """Publish a question; its answer arrives in a later HTTP request."""
        publish = emit or self.emit
        await publish(
            "question_asked",
            {
                "request_id": uuid.uuid4().hex,
                "question": question,
                "choices": list(choices),
                "default": default,
                "kind": kind,
                **(metadata or {}),
            },
        )
        return default

    async def close(self) -> None:
        if self._closed or self._consumer_closed:
            return
        self._closed = True
        await self.queue.put(None)

    async def disconnect(self, reason: str = "client disconnected") -> None:
        """Stop queueing events. The server cancels the harness task."""
        del reason
        if self._consumer_closed:
            return
        self._consumer_closed = True
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
