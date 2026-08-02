"""In-memory event-log implementation used by tests and local callers."""

from typing import List

from core_harness.models.control_plane import ControlPlaneEvent


class InMemoryEventLog:
    """Store control-plane events in process memory."""

    def __init__(self) -> None:
        self._events: List[ControlPlaneEvent] = []

    async def append(self, event: ControlPlaneEvent) -> None:
        self._events.append(event)

    async def list_events(self) -> List[ControlPlaneEvent]:
        return list(self._events)

    @property
    def events(self) -> List[ControlPlaneEvent]:
        return self._events
