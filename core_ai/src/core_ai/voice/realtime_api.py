"""The OpenAI-style realtime protocol xAI and OpenAI share, as one ``VoiceSession`` base.

Both speak ``session.update`` / ``conversation.item.create`` / ``response.create`` and the
server events in ``core_ai.voice.realtime_events``, authenticated with a Bearer key on
``wss://…/realtime?model=``. A provider supplies its ``session`` payload and how input audio
goes on the wire. ``websockets`` is imported when a session opens, so importing core_ai never
loads it (the coding agent's startup budget checks this).
"""

import asyncio
import base64
import json
import logging
from abc import abstractmethod
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, Literal, Optional, TypeVar, Union

from pydantic import ValidationError

from core_ai.voice.realtime_events import (
    HANDLED,
    AudioDeltaEvent,
    DoneResponse,
    Envelope,
    FunctionCallDone,
    OutputItemDone,
    ResponseCreated,
    ResponseDoneEvent,
    SpeechStartedEvent,
    SpeechStoppedEvent,
    TranscriptDelta,
    TranscriptionCompleted,
    Usage,
    server_event,
)
from core_ai.voice.responses import ResponseRouter
from core_ai.voice.session import (
    AudioDelta,
    FrameObserver,
    ResponseDone,
    ResponseEvent,
    SpeechStarted,
    SpeechStopped,
    TextDelta,
    ToolCall,
    UserTranscript,
    VoiceClosed,
    VoiceConfig,
    VoiceError,
    VoiceEvent,
    VoiceSession,
)

if TYPE_CHECKING:
    from websockets.asyncio.client import ClientConnection

log = logging.getLogger(__name__)

SessionT = TypeVar("SessionT", bound="RealtimeApiSession")


class RealtimeApiSession(VoiceSession):
    """One realtime connection. ``response()`` yields only requested responses (see
    ``core_ai.voice.responses``)."""

    def __init__(
        self,
        connection: "ClientConnection",
        model_id: str,
        config: VoiceConfig,
        observer: Optional[FrameObserver] = None,
    ) -> None:
        self.connection = connection
        self.model_id = model_id
        self.config = config
        self.observer = observer
        self._events: asyncio.Queue[VoiceEvent] = asyncio.Queue()
        self._responses = ResponseRouter()
        self._calls: set[str] = set()
        self._reader: Optional[asyncio.Task[None]] = None

    @classmethod
    async def open(
        cls: type[SessionT],
        url: str,
        api_key: str,
        model_id: str,
        config: VoiceConfig,
        observer: Optional[FrameObserver] = None,
    ) -> SessionT:
        from websockets.asyncio.client import connect

        connection = await connect(
            f"{url}?model={model_id}",
            additional_headers={"Authorization": f"Bearer {api_key}"},
            max_size=None,
        )
        session = cls(connection, model_id, config, observer)
        await session._send({"type": "session.update", "session": session.session_payload(config)})
        session._reader = asyncio.create_task(session._read())
        return session

    @abstractmethod
    def session_payload(self, config: VoiceConfig) -> dict[str, Any]:
        """The provider's ``session`` object of a ``session.update`` for ``config``."""

    async def add_message(self, role: Literal["user", "assistant"], text: str) -> None:
        part = "input_text" if role == "user" else "output_text"
        await self._add_item({"type": "message", "role": role, "content": [{"type": part, "text": text}]})

    async def add_tool_call(self, call_id: str, name: str, arguments: str) -> None:
        await self._add_item({"type": "function_call", "call_id": call_id, "name": name, "arguments": arguments})

    async def add_tool_result(self, call_id: str, output: str) -> None:
        await self._add_item({"type": "function_call_output", "call_id": call_id, "output": output})

    async def respond(self) -> None:
        request_id = self._responses.request()
        await self._send({"type": "response.create", "response": {"metadata": {"request_id": request_id}}})

    async def cancel(self) -> None:
        # The cancelled id stays current until the next response.created, so audio still in
        # flight for it is dropped with it.
        if self._responses.cancel_current():
            await self._send({"type": "response.cancel"})

    async def update(self, config: VoiceConfig) -> None:
        self.config = config
        await self._send({"type": "session.update", "session": self.session_payload(config)})

    async def events(self) -> AsyncIterator[VoiceEvent]:
        while True:
            event = await self._events.get()
            yield event
            if isinstance(event, VoiceClosed):
                return

    def response(self) -> AsyncIterator[ResponseEvent]:
        return self._responses.next_response()

    async def aclose(self) -> None:
        await self.connection.close()
        if self._reader is not None:
            await self._reader

    async def _add_item(self, item: dict[str, Any]) -> None:
        await self._send({"type": "conversation.item.create", "item": item})

    async def _send(self, payload: dict[str, Any]) -> None:
        frame = json.dumps(payload)
        self._observe_sent(frame)
        await self.connection.send(frame)

    def _observe_sent(self, frame: Union[str, bytes]) -> None:
        if self.observer is not None:
            self.observer("sent", frame)

    async def _read(self) -> None:
        from websockets.exceptions import ConnectionClosed

        try:
            async for frame in self.connection:
                if self.observer is not None:
                    self.observer("received", frame)
                if isinstance(frame, bytes):
                    self._audio(self._responses.current, frame)
                else:
                    self._handle(frame)
        except ConnectionClosed as exc:
            log.info("voice connection closed: %s", exc)
        finally:
            self._responses.close()
            self._events.put_nowait(VoiceClosed())

    def _handle(self, frame: str) -> None:
        envelope = Envelope.model_validate_json(frame)
        if envelope.type not in HANDLED:
            return
        try:
            event = server_event.validate_json(frame)
        except ValidationError as exc:
            log.warning("unreadable %s event: %s", envelope.type, exc)
            return
        if isinstance(event, SpeechStartedEvent):
            self._responses.utterance_started()
            self._events.put_nowait(SpeechStarted())
        elif isinstance(event, SpeechStoppedEvent):
            self._responses.utterance_ended(server_answers=self.config.turn_detection == "server_vad")
            self._events.put_nowait(SpeechStopped())
        elif isinstance(event, TranscriptionCompleted):
            self._events.put_nowait(UserTranscript(event.transcript.strip()))
        elif isinstance(event, ResponseCreated):
            metadata = event.response.metadata
            self._responses.created(
                event.response.id,
                request_id=metadata.request_id if metadata is not None else None,
                server_started=metadata is None,
            )
        elif isinstance(event, TranscriptDelta):
            self._responses.route(event.response_id, TextDelta(event.delta))
        elif isinstance(event, AudioDeltaEvent):
            self._audio(event.response_id, base64.b64decode(event.delta))
        elif isinstance(event, FunctionCallDone):
            self._tool_call(event.response_id, event.call_id, event.name, event.arguments)
        elif isinstance(event, OutputItemDone):
            item = event.item
            if item.type == "function_call" and item.call_id and item.name:
                self._tool_call(event.response_id, item.call_id, item.name, item.arguments or "{}")
        elif isinstance(event, ResponseDoneEvent):
            self._done(event.response)
        else:
            self._events.put_nowait(VoiceError(event.error.message))

    def _audio(self, response_id: Optional[str], audio: bytes) -> None:
        if not self._responses.is_dropped(response_id):
            self._events.put_nowait(AudioDelta(audio))

    def _tool_call(self, response_id: Optional[str], call_id: str, name: str, arguments: str) -> None:
        """A call is reported twice (arguments.done and output_item.done); keep the first."""
        if call_id in self._calls:
            return
        self._calls.add(call_id)
        self._responses.route(response_id, ToolCall(call_id, name, arguments))

    def _done(self, response: DoneResponse) -> None:
        usage = response.usage or Usage()
        failed = response.status == "failed"
        reason = response.status_details.reason if response.status_details else None
        self._responses.done(
            response.id,
            ResponseDone(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                error=(reason or "failed") if failed else None,
            ),
        )


def realtime_url(base_url: str) -> str:
    """``wss://…/realtime`` on the same host as a REST base URL."""
    scheme, rest = base_url.split("://", 1)
    return f"{'wss' if scheme == 'https' else 'ws'}://{rest}/realtime"
