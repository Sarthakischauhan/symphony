"""Event sink for harness runs.

The loop writes typed events here so a UI can render them. It does not
authorize tools or cancel runs. Cancel a run by cancelling the task that
is awaiting ``CoreHarness.run``.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol, Sequence, Union

from core_harness.models import ControlPlaneEvent, ControlPlaneEventType

Emit = Callable[[str, Dict[str, Any]], Awaitable[None]]


def normalize_event_type(event_type: Union[str, ControlPlaneEventType]) -> str:
    if isinstance(event_type, ControlPlaneEventType):
        return event_type.value
    return event_type


class EventSink:
    """In-memory event log. The default when no UI is attached.

    Subclass and override ``emit`` to stream events (TUI, SSE). Override
    ``request_user_input`` when a product tool such as ``ask_user`` should
    block on a human.
    """

    events: List[ControlPlaneEvent]

    def __init__(self) -> None:
        self.events = []

    async def emit(
        self,
        event_type: Union[str, ControlPlaneEventType],
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.events.append(
            ControlPlaneEvent.typed(normalize_event_type(event_type), payload or {})
        )

    async def request_user_input(
        self,
        *,
        question: str,
        choices: Sequence[str] = (),
        default: str = "",
        kind: str = "question",
        metadata: Optional[Dict[str, Any]] = None,
        emit: Optional[Emit] = None,
    ) -> str:
        del question, choices, kind, metadata, emit
        return default


class EventLog(Protocol):
    """Append-only journal for stamped harness events."""

    async def append_event(self, *, event_type: str, payload: Dict[str, Any]) -> None:
        ...


__all__ = [
    "EventLog",
    "EventSink",
    "normalize_event_type",
]
