"""Event sink for harness runs.

The loop writes typed events here so a UI can render them. It does not
authorize tools or cancel runs. Clients stop or steer a run by sending an
operation to ``CoreHarness.submit`` (see ``core_harness.ops``).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol, Sequence, Union

from core_harness.models import ControlPlaneEvent, ControlPlaneEventType

Emit = Callable[[str, Dict[str, Any]], Awaitable[None]]

logger = logging.getLogger(__name__)


def normalize_event_type(event_type: Union[str, ControlPlaneEventType]) -> str:
    if isinstance(event_type, ControlPlaneEventType):
        return event_type.value
    return event_type


Listener = Callable[[str, Dict[str, Any]], None]


class InteractionPort:
    """Answers the questions a run puts to a human.

    A sink has exactly one. Events fan out to any number of listeners; a
    question has a single responder, and this is it. The default has no
    human and returns ``default``. Subclass it when a product tool such as
    ``ask_user`` should block on a person: ``expect`` a request id, publish
    the question, and await the future. ``CoreHarness.submit(Answer(...))``
    resolves it through ``answer``.
    """

    pending: Dict[str, "asyncio.Future[str]"]

    def __init__(self) -> None:
        self.pending = {}

    def expect(self, request_id: str) -> "asyncio.Future[str]":
        """The future for one question, created on first use."""
        future = self.pending.get(request_id)
        if future is None:
            future = asyncio.get_running_loop().create_future()
            self.pending[request_id] = future
        return future

    def answer(self, request_id: str, value: str = "") -> bool:
        """Resolve a pending question. False when nothing was waiting on it."""
        future = self.pending.get(request_id)
        if future is None or future.done():
            return False
        future.set_result(value)
        return True

    def dismiss(self, value: str = "") -> None:
        """Answer every pending question with ``value``."""
        for future in list(self.pending.values()):
            if not future.done():
                future.set_result(value)

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


class HumanInteraction(InteractionPort):
    """Ask a person through the event stream and wait for an ``Answer`` op.

    Publishes ``question_asked`` on its sink, so every client sees the same
    question the same way, then waits for the answer to that ``request_id``.
    One question is open at a time. A child sink gets a ``fork`` of this
    port: it publishes on the child and is answered through the parent.
    """

    def __init__(self, sink: "EventSink") -> None:
        super().__init__()
        self.sink = sink
        self._lock = asyncio.Lock()

    def fork(self, sink: "EventSink") -> "HumanInteraction":
        child = type(self)(sink)
        child._lock = self._lock
        child.pending = self.pending
        return child

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
        async with self._lock:
            request_id = uuid.uuid4().hex
            future = self.expect(request_id)
            try:
                await (emit or self.sink.emit)(
                    ControlPlaneEventType.QUESTION_ASKED.value,
                    {
                        "request_id": request_id,
                        "question": question,
                        "choices": list(choices),
                        "default": default,
                        "kind": kind,
                        **(metadata or {}),
                    },
                )
                return await future
            finally:
                self.pending.pop(request_id, None)


class EventSink:
    """In-memory event log. The default when no UI is attached.

    Subclass and override ``deliver`` to stream events (TUI, SSE). ``emit``
    calls it, then hands the same event to every ``subscribe`` listener.
    Questions for a human go through ``interaction``, not through the sink.
    """

    events: List[ControlPlaneEvent]
    interaction: InteractionPort

    def __init__(self, interaction: Optional[InteractionPort] = None) -> None:
        self.events = []
        self.interaction = interaction or InteractionPort()
        self._listeners: List[Listener] = []

    async def emit(
        self,
        event_type: Union[str, ControlPlaneEventType],
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        event_name = normalize_event_type(event_type)
        body = payload or {}
        await self.deliver(event_name, body)
        self.notify(event_name, body)

    async def deliver(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Hand one event to this sink's own consumer."""
        self.events.append(ControlPlaneEvent.typed(event_type, payload))

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        """Add a read-only listener. Returns a function that removes it.

        Listeners run inline on the run's loop, so they must return at once:
        filter, enqueue, and do the slow work elsewhere. They cannot answer
        questions or stop a tool.
        """
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def notify(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Call every listener. A failing listener never fails the run."""
        for listener in tuple(self._listeners):
            try:
                listener(event_type, payload)
            except Exception:
                logger.exception("event listener failed on %s", event_type)


class EventLog(Protocol):
    """Append-only journal for stamped harness events."""

    async def append_event(self, *, event_type: str, payload: Dict[str, Any]) -> None:
        ...


__all__ = [
    "EventLog",
    "EventSink",
    "HumanInteraction",
    "InteractionPort",
    "normalize_event_type",
]
