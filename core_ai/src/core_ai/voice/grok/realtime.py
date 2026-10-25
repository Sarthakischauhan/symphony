"""xAI speech-to-speech sessions over ``wss://api.x.ai/v1/realtime``.

Event names follow https://docs.x.ai/developers/rest-api-reference/inference/voice. Audio goes
both ways as binary frames; everything else is JSON. ``websockets`` is imported when a session
opens, so importing core_ai never loads it (the coding agent's startup budget checks this).
"""

import asyncio
import base64
import json
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, Literal, Optional, Union

from pydantic import ValidationError

from core_ai.voice.grok.events import (
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
from core_ai.voice.grok.payload import realtime_url, session_payload
from core_ai.voice.grok.responses import ResponseRouter
from core_ai.voice.registry import VoiceProvider
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


class GrokRealtime(VoiceProvider):
    """xAI's realtime voice models, on the key and base URL of an xAI account."""

    def __init__(self, api_key: str, base_url: str = "https://api.x.ai/v1") -> None:
        self.api_key = api_key
        self.base_url = base_url

    async def open(
        self,
        model_name: str,
        config: VoiceConfig,
        observer: Optional[FrameObserver] = None,
    ) -> VoiceSession:
        return await GrokVoiceSession.open(realtime_url(self.base_url), self.api_key, model_name, config, observer)


class GrokVoiceSession(VoiceSession):
    """One xAI realtime connection. ``response()`` yields only requested responses (see
    ``core_ai.voice.grok.responses``)."""

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
        cls,
        url: str,
        api_key: str,
        model_id: str,
        config: VoiceConfig,
        observer: Optional[FrameObserver] = None,
    ) -> "GrokVoiceSession":
        from websockets.asyncio.client import connect

        connection = await connect(
            f"{url}?model={model_id}",
            additional_headers={"Authorization": f"Bearer {api_key}"},
            max_size=None,
        )
        session = cls(connection, model_id, config, observer)
        await session._send({"type": "session.update", "session": session_payload(config)})
        session._reader = asyncio.create_task(session._read())
        return session

    async def send_audio(self, audio: bytes) -> None:
        self._observe_sent(audio)
        await self.connection.send(audio)

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
        # The cancelled id stays current until the next response.created, so binary audio
        # frames still in flight for it are dropped with it.
        if self._responses.cancel_current():
            await self._send({"type": "response.cancel"})

    async def update(self, config: VoiceConfig) -> None:
        self.config = config
        await self._send({"type": "session.update", "session": session_payload(config)})

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
            self._responses.created(event.response)
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
        """xAI reports a call twice (arguments.done and output_item.done); keep the first."""
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
