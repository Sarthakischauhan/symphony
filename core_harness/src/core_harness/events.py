"""Control-plane base, event logs, and concrete emitters."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol, Sequence, Union

from core_harness.models import (
    EVENT_SCHEMA_VERSION,
    ControlCommand,
    ControlCommandType,
    ControlPlaneEvent,
    ControlPlaneEventType,
)

Emit = Callable[[str, Dict[str, Any]], Awaitable[None]]


class ControlPlane:
    """Runtime orchestration boundary with typed interaction methods.

    Callers invoke these methods directly. Missing overrides use the
    fail-closed defaults here; do not ``getattr``-probe for optional hooks.
    """

    async def emit(
        self,
        event_type: Union[str, ControlPlaneEventType],
        payload: Dict[str, Any],
    ) -> None:
        del event_type, payload
        return None

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

    async def approve_tool_call(
        self,
        *,
        tool_name: str,
        arguments: Dict[str, Any],
        emit: Optional[Emit] = None,
    ) -> bool:
        del tool_name, arguments, emit
        return False

    async def send_command(self, command: ControlCommand) -> None:
        del command
        return None

    async def drain_commands(self) -> List[ControlCommand]:
        return []

    async def wait_if_paused(self) -> None:
        return None

    cancelled: bool = False
    cancel_reason: str = "cancelled"
    cancel_event: Optional[asyncio.Event] = None
    paused: bool = False


class EventLog(Protocol):
    """Append-only journal for identified control-plane events."""

    async def append_event(self, *, event_type: str, payload: Dict[str, Any]) -> None:
        ...


def normalize_event_type(event_type: Union[str, ControlPlaneEventType]) -> str:
    """Return the string value used by event models and subscribers."""
    if isinstance(event_type, ControlPlaneEventType):
        return event_type.value
    return event_type


class InMemoryEventLog:
    """Store control-plane events in process memory."""

    def __init__(self) -> None:
        self._events: List[ControlPlaneEvent] = []

    async def append_event(self, *, event_type: str, payload: Dict[str, Any]) -> None:
        self._events.append(ControlPlaneEvent.typed(event_type, payload))

    async def list_events(self) -> List[ControlPlaneEvent]:
        return list(self._events)

    @property
    def events(self) -> List[ControlPlaneEvent]:
        return self._events


class IdentifiedControlPlane(ControlPlane):
    """Wrap an inner plane and attach run_id, session_id, seq, ts, schema_version."""

    def __init__(
        self,
        inner: ControlPlane,
        *,
        run_id: str,
        session_id: str,
        schema_version: int = EVENT_SCHEMA_VERSION,
        agent_id: Optional[str] = None,
        parent_id: Optional[str] = None,
        persistence: Optional[EventLog] = None,
    ) -> None:
        self.inner = inner
        self.run_id = run_id
        self.session_id = session_id
        self.schema_version = schema_version
        self.agent_id = agent_id or run_id
        self.parent_id = parent_id
        self.persistence = persistence
        self._sequence = 0

    async def emit(
        self,
        event_type: Union[str, ControlPlaneEventType],
        payload: Dict[str, Any],
    ) -> None:
        self._sequence += 1
        stamped = {
            **(payload or {}),
            "run_id": self.run_id,
            "session_id": self.session_id,
            "seq": self._sequence,
            "ts": time.time(),
            "schema_version": self.schema_version,
            "agent_id": self.agent_id,
            "parent_id": self.parent_id,
        }
        event_name = normalize_event_type(event_type)
        if self.persistence is not None:
            await self.persistence.append_event(event_type=event_name, payload=stamped)
        await self.inner.emit(event_name, stamped)

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
        return str(
            await self.inner.request_user_input(
                question=question,
                choices=choices,
                default=default,
                kind=kind,
                metadata=metadata,
                emit=emit or self.emit,
            )
            or ""
        )

    async def approve_tool_call(
        self,
        *,
        tool_name: str,
        arguments: Dict[str, Any],
        emit: Optional[Emit] = None,
    ) -> bool:
        return bool(
            await self.inner.approve_tool_call(
                tool_name=tool_name,
                arguments=arguments,
                emit=emit or self.emit,
            )
        )

    async def send_command(self, command: ControlCommand) -> None:
        await self.inner.send_command(command)

    async def drain_commands(self) -> List[ControlCommand]:
        return await self.inner.drain_commands()

    async def wait_if_paused(self) -> None:
        await self.inner.wait_if_paused()

    @property
    def cancelled(self) -> bool:
        return self.inner.cancelled

    @property
    def cancel_reason(self) -> str:
        return self.inner.cancel_reason

    @property
    def cancel_event(self) -> Optional[asyncio.Event]:
        return self.inner.cancel_event

    @property
    def paused(self) -> bool:
        return self.inner.paused


class NullControlPlane(ControlPlane):
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
        self._cancel_event: Optional[asyncio.Event] = None

    def _loop_event(self, current: Optional[asyncio.Event], *, set_when: bool) -> asyncio.Event:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            if current is None:
                current = asyncio.Event()
                if set_when:
                    current.set()
            return current
        if current is None:
            current = asyncio.Event()
            if set_when:
                current.set()
            return current
        getter = getattr(current, "_get_loop", None)
        bound = None
        if getter is not None:
            try:
                bound = getter()
            except RuntimeError:
                bound = None
        if bound is not loop:
            current = asyncio.Event()
            if set_when:
                current.set()
        return current

    @property
    def cancel_event(self) -> asyncio.Event:
        self._cancel_event = self._loop_event(self._cancel_event, set_when=self._cancelled)
        return self._cancel_event

    async def emit(
        self,
        event_type: Union[str, ControlPlaneEventType],
        payload: Dict[str, Any],
    ) -> None:
        self.events.append(
            ControlPlaneEvent.typed(normalize_event_type(event_type), payload)
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

    async def approve_tool_call(
        self,
        *,
        tool_name: str,
        arguments: Dict[str, Any],
        emit: Optional[Emit] = None,
    ) -> bool:
        del tool_name, arguments, emit
        return True

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


__all__ = [
    "ControlPlane",
    "EventLog",
    "IdentifiedControlPlane",
    "InMemoryEventLog",
    "NullControlPlane",
    "normalize_event_type",
]
