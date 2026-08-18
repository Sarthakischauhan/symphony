"""Concrete control-plane emitters for recording, fan-out, and persistence."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

from core_harness.control_plane.base import (
    ControlPlane,
    EventLog,
    normalize_event_type,
)
from core_harness.models.control_plane import (
    ControlCommand,
    ControlCommandType,
    ControlPlaneEvent,
    ControlPlaneEventType,
)


class NullControlPlane:
    """Recording default emitter that also supports inbound commands."""

    events: List[ControlPlaneEvent]

    def __init__(self) -> None:
        self.events = []
        self._commands: List[ControlCommand] = []
        self._paused = False
        self._resume_event = asyncio.Event()
        self._resume_event.set()
        self._cancelled = False
        self._cancel_reason = "cancelled"
        self.cancel_event = asyncio.Event()

    async def emit(
        self,
        event_type: Union[str, ControlPlaneEventType],
        payload: Dict[str, Any],
    ) -> None:
        self.events.append(
            ControlPlaneEvent.typed(normalize_event_type(event_type), payload)
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
        if command.type == ControlCommandType.CANCEL:
            self._cancelled = True
            self._cancel_reason = str(command.payload.get("reason", "cancelled"))
            self.cancel_event.set()
        self._commands.append(command)

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def cancel_reason(self) -> str:
        return self._cancel_reason

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
    """Send every event to an ordered set of subscriber planes."""

    def __init__(self, subscribers: Sequence[ControlPlane]) -> None:
        if not subscribers:
            raise ValueError("FanoutControlPlane requires at least one subscriber.")
        self.subscribers = list(subscribers)

    async def emit(
        self,
        event_type: Union[str, ControlPlaneEventType],
        payload: Dict[str, Any],
    ) -> None:
        normalized = normalize_event_type(event_type)
        for subscriber in self.subscribers:
            await subscriber.emit(normalized, payload)


class PersistingControlPlane:
    """Append every emitted event to an event-log adapter."""

    def __init__(self, event_log: EventLog) -> None:
        self.event_log = event_log

    async def emit(
        self,
        event_type: Union[str, ControlPlaneEventType],
        payload: Dict[str, Any],
    ) -> None:
        await self.event_log.append(
            ControlPlaneEvent.typed(normalize_event_type(event_type), payload)
        )


class InteractiveControlPlane(NullControlPlane):
    """Recording emitter with optional event-log and subscriber fan-out."""

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
        normalized = normalize_event_type(event_type)
        event = ControlPlaneEvent.typed(normalized, payload)
        self.events.append(event)
        if self.event_log is not None:
            await self.event_log.append(event)
        for subscriber in self._extra_subscribers:
            await subscriber.emit(normalized, payload)
