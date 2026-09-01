"""Control-plane protocols, event logs, and concrete emitters."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Protocol, Sequence, Union

from core_harness.models import (
    EVENT_SCHEMA_VERSION,
    ControlCommand,
    ControlCommandType,
    ControlPlaneEvent,
    ControlPlaneEventType,
)

# --- base.py ---
class ControlPlane(Protocol):
    """Runtime orchestration boundary; ``emit`` is its minimum capability."""

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


Emit = Callable[[str, Dict[str, Any]], Awaitable[None]]


class InteractiveControlPlaneProtocol(ControlPlane, Protocol):
    """Control plane that owns user interaction and tool authorization."""

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
        ...

    async def approve_tool_call(
        self,
        *,
        tool_name: str,
        arguments: Dict[str, Any],
        emit: Optional[Emit] = None,
    ) -> bool:
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

# --- event_log.py ---
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

# --- identity.py ---
class IdentifiedControlPlane:
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
    ) -> None:
        self.inner = inner
        self.run_id = run_id
        self.session_id = session_id
        self.schema_version = schema_version
        self.agent_id = agent_id or run_id
        self.parent_id = parent_id
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
        await self.inner.emit(normalize_event_type(event_type), stamped)

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
        request = getattr(self.inner, "request_user_input", None)
        if not callable(request):
            return default
        return str(
            await request(
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
        approve = getattr(self.inner, "approve_tool_call", None)
        if not callable(approve):
            return True
        return bool(
            await approve(
                tool_name=tool_name,
                arguments=arguments,
                emit=emit or self.emit,
            )
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

# --- emitter.py ---
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

__all__ = [
    "ControlPlane",
    "EventLog",
    "FanoutControlPlane",
    "IdentifiedControlPlane",
    "InboundControlPlane",
    "InMemoryEventLog",
    "InteractiveControlPlane",
    "InteractiveControlPlaneProtocol",
    "NullControlPlane",
    "PersistingControlPlane",
    "normalize_event_type",
]
