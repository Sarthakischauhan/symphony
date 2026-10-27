"""Which responses on a realtime connection were asked for, and where their events go.

Shared by every provider client. Correlation is protocol-level only (no turns, no history):
``request()`` names a requested response. Protocols that echo it (xAI, OpenAI: the
``request_id`` in ``response.created`` metadata) pass it to ``created``; protocols that don't
(AI Gateway, Gemini Live) pass ``oldest_request()``, since responses start in request order.
With server VAD the utterance ``speech_stopped`` ended is answered by a server-started response
until the next ``speech_started`` begins a new utterance. That
``speech_started`` is the protocol's end of an unanswered utterance, so a turn the server
never answers leaves nothing pending. Anything else is dropped.
"""

import asyncio
import itertools
import logging
from collections.abc import AsyncIterator
from typing import Optional

from core_ai.voice.session import ResponseDone, ResponseEvent

log = logging.getLogger(__name__)

CLOSED = "the voice connection closed"


class ResponseRouter:
    """Requested responses in creation order, each with its own event buffer."""

    def __init__(self) -> None:
        self._ids = itertools.count(1)
        self._requested: dict[str, None] = {}
        self._utterance_open = False
        self._accepted: asyncio.Queue[Optional[str]] = asyncio.Queue()
        self._buffers: dict[str, asyncio.Queue[ResponseEvent]] = {}
        self.current: Optional[str] = None
        self._dropped: set[str] = set()

    def request(self) -> str:
        """A new ``request_id`` for the metadata of a ``response.create``."""
        request_id = f"req-{next(self._ids)}"
        self._requested[request_id] = None
        return request_id

    def utterance_started(self) -> None:
        self._utterance_open = False

    def utterance_ended(self, server_answers: bool) -> None:
        self._utterance_open = server_answers

    def oldest_request(self) -> Optional[str]:
        """The longest-waiting unanswered request, for protocols that echo no request id."""
        return next(iter(self._requested), None)

    def created(self, response_id: str, request_id: Optional[str], server_started: bool) -> None:
        """A response began: ``request_id`` it answers, or ``server_started`` by server VAD."""
        self.current = response_id
        if not self._claim(request_id, server_started):
            log.debug("dropping unrequested voice response %s", response_id)
            self._dropped.add(response_id)
            return
        self._buffers[response_id] = asyncio.Queue()
        self._accepted.put_nowait(response_id)

    def _claim(self, request_id: Optional[str], server_started: bool) -> bool:
        if request_id is not None and request_id in self._requested:
            del self._requested[request_id]
            return True
        if server_started and self._utterance_open:
            self._utterance_open = False
            return True
        return False

    def cancel_current(self) -> bool:
        """Drop the response in flight; False when there is none to cancel."""
        if self.current is None or self.current in self._dropped:
            return False
        self._dropped.add(self.current)
        return True

    def is_dropped(self, response_id: Optional[str]) -> bool:
        return response_id is not None and response_id in self._dropped

    def route(self, response_id: Optional[str], event: ResponseEvent) -> None:
        """Hand an event to its requested response; others are dropped."""
        response_id = response_id or self.current
        queue = self._buffers.get(response_id) if response_id is not None else None
        if queue is None:
            return
        if response_id in self._dropped and not isinstance(event, ResponseDone):
            return
        queue.put_nowait(event)

    def done(self, response_id: Optional[str], event: ResponseDone) -> None:
        if response_id == self.current:
            self.current = None
        self.route(response_id, event)

    def close(self) -> None:
        """End every open response, and every later ``next_response``, with a closed error."""
        for queue in self._buffers.values():
            queue.put_nowait(ResponseDone(error=CLOSED))
        self._accepted.put_nowait(None)

    async def next_response(self) -> AsyncIterator[ResponseEvent]:
        while True:
            response_id = await self._accepted.get()
            if response_id is None:
                self._accepted.put_nowait(None)
                yield ResponseDone(error=CLOSED)
                return
            if response_id in self._dropped:
                self._buffers.pop(response_id, None)  # cancelled before anyone read it
                continue
            queue = self._buffers[response_id]
            try:
                while True:
                    event = await queue.get()
                    yield event
                    if isinstance(event, ResponseDone):
                        return
            finally:
                self._buffers.pop(response_id, None)
