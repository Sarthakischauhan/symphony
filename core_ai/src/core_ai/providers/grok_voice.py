"""xAI Voice Agent (realtime) sessions over ``wss://api.x.ai/v1/realtime``.

Event names follow https://docs.x.ai/developers/model-capabilities/audio/voice-agent. Audio goes
both ways as binary frames; everything else is JSON. ``websockets`` is imported when a session
opens, so importing core_ai never loads it (the coding agent's startup budget checks this).
"""

import asyncio
import base64
import json
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from core_ai.models.types import AudioFormat
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
    VoiceHistory,
    VoiceSession,
)

if TYPE_CHECKING:
    from websockets.asyncio.client import ClientConnection

log = logging.getLogger(__name__)

_AUDIO_TYPES: dict[str, str] = {
    "pcm16": "audio/pcm",
    "pcmu": "audio/pcmu",
    "pcma": "audio/pcma",
}


class _Incoming(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _SpeechStarted(_Incoming):
    type: Literal["input_audio_buffer.speech_started"]


class _SpeechStopped(_Incoming):
    type: Literal["input_audio_buffer.speech_stopped"]


class _TranscriptionCompleted(_Incoming):
    type: Literal["conversation.item.input_audio_transcription.completed"]
    transcript: str = ""


class _ResponseRef(_Incoming):
    id: str


class _ResponseCreated(_Incoming):
    type: Literal["response.created"]
    response: _ResponseRef


class _TranscriptDelta(_Incoming):
    type: Literal["response.output_audio_transcript.delta"]
    response_id: Optional[str] = None
    delta: str


class _AudioDelta(_Incoming):
    type: Literal["response.output_audio.delta"]
    response_id: Optional[str] = None
    delta: str


class _FunctionCallDone(_Incoming):
    type: Literal["response.function_call_arguments.done"]
    response_id: Optional[str] = None
    call_id: str
    name: str
    arguments: str


class _OutputItem(_Incoming):
    type: str
    call_id: Optional[str] = None
    name: Optional[str] = None
    arguments: Optional[str] = None


class _OutputItemDone(_Incoming):
    type: Literal["response.output_item.done"]
    response_id: Optional[str] = None
    item: _OutputItem


class _Usage(_Incoming):
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


class _StatusDetails(_Incoming):
    reason: Optional[str] = None


class _DoneResponse(_Incoming):
    id: Optional[str] = None
    status: Optional[str] = None
    status_details: Optional[_StatusDetails] = None
    usage: Optional[_Usage] = None


class _ResponseDone(_Incoming):
    type: Literal["response.done"]
    response: _DoneResponse = _DoneResponse()


class _ErrorDetail(_Incoming):
    message: str = "unknown error"


class _Error(_Incoming):
    type: Literal["error"]
    error: _ErrorDetail = _ErrorDetail()


class _Other(_Incoming):
    type: str


_ServerEvent = Annotated[
    Union[
        _SpeechStarted,
        _SpeechStopped,
        _TranscriptionCompleted,
        _ResponseCreated,
        _TranscriptDelta,
        _AudioDelta,
        _FunctionCallDone,
        _OutputItemDone,
        _ResponseDone,
        _Error,
    ],
    Field(discriminator="type"),
]
_server_event: TypeAdapter[_ServerEvent] = TypeAdapter(_ServerEvent)
_HANDLED = frozenset(
    {
        "input_audio_buffer.speech_started",
        "input_audio_buffer.speech_stopped",
        "conversation.item.input_audio_transcription.completed",
        "response.created",
        "response.output_audio_transcript.delta",
        "response.output_audio.delta",
        "response.function_call_arguments.done",
        "response.output_item.done",
        "response.done",
        "error",
    }
)


def _audio_config(audio: AudioFormat) -> dict[str, Any]:
    direction = {
        "format": {"type": _AUDIO_TYPES[audio.encoding], "rate": audio.sample_rate},
        "transport": "binary",
    }
    return {"input": direction, "output": direction}


def session_payload(config: VoiceConfig) -> dict[str, Any]:
    """The ``session`` object of a ``session.update`` for this config."""
    session: dict[str, Any] = {
        "voice": config.voice,
        "instructions": config.instructions,
        "turn_detection": {"type": "server_vad"}
        if config.turn_detection == "server_vad"
        else None,
        "audio": _audio_config(config.audio),
        "tools": [{"type": "function", **tool} for tool in config.tools],
    }
    if config.reasoning_effort is not None:
        session["reasoning"] = {"effort": config.reasoning_effort}
    return session


class GrokVoiceSession(VoiceSession):
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
        self.history = VoiceHistory()
        self.observer = observer
        self._events: asyncio.Queue[VoiceEvent] = asyncio.Queue()
        self._responses: asyncio.Queue[tuple[Optional[str], ResponseEvent]] = (
            asyncio.Queue()
        )
        self._current: Optional[str] = None
        self._dropped: set[str] = set()
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
        await self._send(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": role,
                    "content": [{"type": part, "text": text}],
                },
            }
        )

    async def add_tool_result(self, call_id: str, output: str) -> None:
        await self._send(
            {
                "type": "conversation.item.create",
                "item": {"type": "function_call_output", "call_id": call_id, "output": output},
            }
        )

    async def respond(self) -> None:
        await self._send({"type": "response.create"})

    async def cancel(self) -> None:
        if self._current is None:
            return
        self._dropped.add(self._current)
        self._current = None
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

    async def response(self) -> AsyncIterator[ResponseEvent]:
        while True:
            response_id, event = await self._responses.get()
            if response_id is not None and response_id in self._dropped:
                continue
            yield event
            if isinstance(event, ResponseDone):
                return

    async def aclose(self) -> None:
        await self.connection.close()
        if self._reader is not None:
            await self._reader

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
                    self._audio(self._current, frame)
                else:
                    self._handle(frame)
        except ConnectionClosed as exc:
            log.info("voice connection closed: %s", exc)
        finally:
            self._responses.put_nowait(
                (None, ResponseDone(error="the voice connection closed"))
            )
            self._events.put_nowait(VoiceClosed())

    def _handle(self, frame: str) -> None:
        envelope = _Other.model_validate_json(frame)
        if envelope.type not in _HANDLED:
            return
        try:
            event = _server_event.validate_json(frame)
        except ValidationError as exc:
            log.warning("unreadable %s event: %s", envelope.type, exc)
            return
        if isinstance(event, _SpeechStarted):
            self._events.put_nowait(SpeechStarted())
        elif isinstance(event, _SpeechStopped):
            self._events.put_nowait(SpeechStopped())
        elif isinstance(event, _TranscriptionCompleted):
            self._heard(event.transcript.strip())
        elif isinstance(event, _ResponseCreated):
            self._current = event.response.id
        elif isinstance(event, _TranscriptDelta):
            self._responses.put_nowait((event.response_id, TextDelta(event.delta)))
        elif isinstance(event, _AudioDelta):
            self._audio(event.response_id, base64.b64decode(event.delta))
        elif isinstance(event, _FunctionCallDone):
            self._tool_call(event.response_id, event.call_id, event.name, event.arguments)
        elif isinstance(event, _OutputItemDone):
            item = event.item
            if item.type == "function_call" and item.call_id and item.name:
                self._tool_call(event.response_id, item.call_id, item.name, item.arguments or "{}")
        elif isinstance(event, _ResponseDone):
            self._done(event.response)
        else:
            self._events.put_nowait(VoiceError(event.error.message))

    def _heard(self, text: str) -> None:
        if text:
            self.history.heard.append(text)
        self._events.put_nowait(UserTranscript(text))

    def _audio(self, response_id: Optional[str], audio: bytes) -> None:
        if response_id is None or response_id not in self._dropped:
            self._events.put_nowait(AudioDelta(audio))

    def _tool_call(
        self, response_id: Optional[str], call_id: str, name: str, arguments: str
    ) -> None:
        """xAI reports a call twice (arguments.done and output_item.done); keep the first."""
        if call_id in self._calls:
            return
        self._calls.add(call_id)
        self._responses.put_nowait((response_id, ToolCall(call_id, name, arguments)))

    def _done(self, response: _DoneResponse) -> None:
        if response.id == self._current:
            self._current = None
        usage = response.usage or _Usage()
        failed = response.status == "failed"
        reason = response.status_details.reason if response.status_details else None
        self._responses.put_nowait(
            (
                response.id,
                ResponseDone(
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    error=(reason or "failed") if failed else None,
                ),
            )
        )

