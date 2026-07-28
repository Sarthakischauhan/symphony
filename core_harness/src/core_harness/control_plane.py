"""Control-plane product surface: fan-out, persistence, and inbound commands."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence, Union

from core_harness.models.control_plane import (
    ControlCommand,
    ControlCommandType,
    ControlPlaneEvent,
    ControlPlaneEventType,
)


class ControlPlane(Protocol):
    async def emit(
        self,
        event_type: Union[str, ControlPlaneEventType],
        payload: Dict[str, Any],
    ) -> None:
        """Receive harness lifecycle and tool execution events."""


class InboundControlPlane(ControlPlane, Protocol):
    """Outbound emit plus inbound command queue (cancel / pause / inject)."""

    async def send_command(self, command: ControlCommand) -> None:
        """Enqueue an inbound control command for the harness to observe."""

    async def drain_commands(self) -> List[ControlCommand]:
        """Return and clear pending inbound commands."""


class EventLog(Protocol):
    """Append-only persistence adapter for control-plane events."""

    async def append(self, event: ControlPlaneEvent) -> None:
        ...

    async def list_events(self) -> List[ControlPlaneEvent]:
        ...


class InMemoryEventLog:
    def __init__(self) -> None:
        self._events: List[ControlPlaneEvent] = []

    async def append(self, event: ControlPlaneEvent) -> None:
        self._events.append(event)

    async def list_events(self) -> List[ControlPlaneEvent]:
        return list(self._events)

    @property
    def events(self) -> List[ControlPlaneEvent]:
        return self._events


def _normalize_event_type(event_type: Union[str, ControlPlaneEventType]) -> str:
    if isinstance(event_type, ControlPlaneEventType):
        return event_type.value
    return event_type


class NullControlPlane:
    """Recording sink used by tests and as the default harness plane."""

    events: list[ControlPlaneEvent]

    def __init__(self) -> None:
        self.events = []
        self._commands: List[ControlCommand] = []
        self._paused = False
        self._resume_event = asyncio.Event()
        self._resume_event.set()

    async def emit(
        self,
        event_type: Union[str, ControlPlaneEventType],
        payload: Dict[str, Any],
    ) -> None:
        self.events.append(
            ControlPlaneEvent.typed(_normalize_event_type(event_type), payload)
        )

    async def send_command(self, command: ControlCommand) -> None:
        if command.type == ControlCommandType.RESUME:
            self._paused = False
            self._resume_event.set()
            return
        if command.type == ControlCommandType.PAUSE:
            self._paused = True
            self._resume_event.clear()
            return
        self._commands.append(command)

    async def drain_commands(self) -> List[ControlCommand]:
        commands = list(self._commands)
        self._commands.clear()
        return commands

    async def wait_if_paused(self) -> None:
        await self._resume_event.wait()

    @property
    def paused(self) -> bool:
        return self._paused


class FanoutControlPlane:
    """Fan-out emit to multiple subscriber control planes."""

    def __init__(self, subscribers: Sequence[ControlPlane]) -> None:
        if not subscribers:
            raise ValueError("FanoutControlPlane requires at least one subscriber.")
        self.subscribers = list(subscribers)

    async def emit(
        self,
        event_type: Union[str, ControlPlaneEventType],
        payload: Dict[str, Any],
    ) -> None:
        normalized = _normalize_event_type(event_type)
        for subscriber in self.subscribers:
            await subscriber.emit(normalized, payload)


class PersistingControlPlane:
    """Control plane that appends every event to an EventLog adapter."""

    def __init__(self, event_log: EventLog) -> None:
        self.event_log = event_log

    async def emit(
        self,
        event_type: Union[str, ControlPlaneEventType],
        payload: Dict[str, Any],
    ) -> None:
        await self.event_log.append(
            ControlPlaneEvent.typed(_normalize_event_type(event_type), payload)
        )


class InteractiveControlPlane(NullControlPlane):
    """
    Product-facing plane: records events, persists optionally, and accepts commands.

    Prefer composing with FanoutControlPlane when multiple sinks are needed.
    """

    def __init__(
        self,
        *,
        event_log: Optional[EventLog] = None,
        subscribers: Optional[Iterable[ControlPlane]] = None,
    ) -> None:
        super().__init__()
        self.event_log = event_log
        self._extra_subscribers = list(subscribers or [])

    async def emit(
        self,
        event_type: Union[str, ControlPlaneEventType],
        payload: Dict[str, Any],
    ) -> None:
        normalized = _normalize_event_type(event_type)
        event = ControlPlaneEvent.typed(normalized, payload)
        self.events.append(event)
        if self.event_log is not None:
            await self.event_log.append(event)
        for subscriber in self._extra_subscribers:
            await subscriber.emit(normalized, payload)
