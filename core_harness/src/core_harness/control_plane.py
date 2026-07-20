from typing import Any, Dict, Protocol

from core_harness.models.control_plane import ControlPlaneEvent


class ControlPlane(Protocol):
    async def emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Receive harness lifecycle and tool execution events."""


class NullControlPlane:
    events: list[ControlPlaneEvent]

    def __init__(self) -> None:
        self.events = []

    async def emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        self.events.append(ControlPlaneEvent(event_type=event_type, payload=payload))
