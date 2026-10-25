"""Which responses on a realtime connection were asked for, and where their events go.

Correlation is protocol-level only (no turns, no history): ``request()`` names a
``response.create`` with a ``request_id`` the server echoes in ``response.created``'s
metadata; with server VAD the utterance ``speech_stopped`` ended is answered by a response
with null metadata until the next ``speech_started`` begins a new utterance. That
``speech_started`` is the protocol's end of an unanswered utterance, so a turn the server
never answers leaves nothing pending. Anything else is dropped.
"""

import asyncio
import itertools
import logging
from collections.abc import AsyncIterator
from typing import Optional

from core_ai.voice.grok.events import CreatedResponse, RequestMetadata
from core_ai.voice.session import ResponseDone, ResponseEvent

log = logging.getLogger(__name__)

CLOSED = "the voice connection closed"


class ResponseRouter:
    """Requested responses in creation order, each with its own event buffer."""

    def __init__(self) -> None:
        self._ids = itertools.count(1)
        self._requested: set[str] = set()
        self._utterance_open = False
        self._accepted: asyncio.Queue[Optional[str]] = asyncio.Queue()
        self._buffers: dict[str, asyncio.Queue[ResponseEvent]] = {}
        self.current: Optional[str] = None
        self._dropped: set[str] = set()

    def request(self) -> str:
        """A new ``request_id`` for the metadata of a ``response.create``."""
        request_id = f"req-{next(self._ids)}"
        self._requested.add(request_id)
        return request_id

    def utterance_started(self) -> None:
        self._utterance_open = False

    def utterance_ended(self, server_answers: bool) -> None:
        self._utterance_open = server_answers

    def created(self, response: CreatedResponse) -> None:
        self.current = response.id
        if not self._claim(response.metadata):
            log.debug("dropping unrequested voice response %s", response.id)
            self._dropped.add(response.id)
            return
        self._buffers[response.id] = asyncio.Queue()
        self._accepted.put_nowait(response.id)

    def _claim(self, metadata: Optional[RequestMetadata]) -> bool:
        if metadata is not None and metadata.request_id in self._requested:
            self._requested.discard(metadata.request_id)
            return True
        if metadata is None and self._utterance_open:
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
