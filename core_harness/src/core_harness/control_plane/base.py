"""Protocols shared by control-plane emitters and event-log adapters."""

from typing import Any, Dict, List, Protocol, Union

from core_harness.models.control_plane import (
    ControlCommand,
    ControlPlaneEvent,
    ControlPlaneEventType,
)


class ControlPlane(Protocol):
    """Destination for harness lifecycle and tool execution events."""

    async def emit(
        self,
        event_type: Union[str, ControlPlaneEventType],
        payload: Dict[str, Any],
    ) -> None:
        ...


class InboundControlPlane(ControlPlane, Protocol):
    """Control plane that also accepts commands from a caller or UI."""

    async def send_command(self, command: ControlCommand) -> None:
        ...

    async def drain_commands(self) -> List[ControlCommand]:
        ...


class EventLog(Protocol):
    """Append-only adapter for control-plane events."""

    async def append(self, event: ControlPlaneEvent) -> None:
        ...

    async def list_events(self) -> List[ControlPlaneEvent]:
        ...


def normalize_event_type(event_type: Union[str, ControlPlaneEventType]) -> str:
    """Return the string value used by event models and subscribers."""
    if isinstance(event_type, ControlPlaneEventType):
        return event_type.value
    return event_type
