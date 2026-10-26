"""Gemini Live speech-to-speech sessions over the ``BidiGenerateContent`` WebSocket.

Per https://ai.google.dev/api/live: ``setup`` first, then ``realtimeInput`` audio,
``clientContent`` turns and ``toolResponse``. Live has no response ids, no cancel message and
no mid-session config change, so: a model turn is one response, numbered here, claimed in
request order and ended by ``turnComplete`` (or by a ``toolCall``, after which the model waits
for the ``toolResponse`` and continues on its own); ``cancel`` drops the turn locally; and
``update`` resumes the session on a new connection with the new config (session resumption).
"""

import asyncio
import base64
import itertools
import json
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, Literal, Optional

from pydantic import ValidationError

from core_ai.voice.gemini.events import ServerContent, ServerMessage, ToolCallMessage, UsageMetadata
from core_ai.voice.gemini.payload import GEMINI_LIVE_URL, audio_mime_type, live_url, setup_message
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


class GeminiNotResumable(RuntimeError):
    """Live config can only change through session resumption, and the server has not (yet)
    offered a resumable point (``sessionResumptionUpdate.resumable``)."""


async def open_gemini_live(
    api_key: str,
    model_name: str,
    config: VoiceConfig,
    observer: Optional[FrameObserver] = None,
    base_url: str = GEMINI_LIVE_URL,
) -> "GeminiVoiceSession":
    """Connect to Gemini Live model ``model_name`` with a Gemini API key and apply ``config``."""
    session = GeminiVoiceSession(live_url(base_url, api_key), model_name, config, observer)
    await session.connect(resume_handle=None)
    return session


class GeminiVoiceSession(VoiceSession):
    """One Gemini Live session (possibly across resumed connections)."""

    def __init__(self, url: str, model_id: str, config: VoiceConfig, observer: Optional[FrameObserver] = None) -> None:
        self.url = url
        self.model_id = model_id
        self.config = config
        self.observer = observer
        self.connection: Optional["ClientConnection"] = None
        self._events: asyncio.Queue[VoiceEvent] = asyncio.Queue()
        self._responses = ResponseRouter()
        self._turns = itertools.count(1)
        self._call_names: dict[str, str] = {}
        self._user_text: list[str] = []
        self._usage = UsageMetadata()
        self._resume_handle: Optional[str] = None
        self._in_activity = False
        self._tool_answered = False
        self._reader: Optional[asyncio.Task[None]] = None

    async def connect(self, resume_handle: Optional[str]) -> None:
        from websockets.asyncio.client import connect

        self.connection = await connect(self.url, max_size=None)
        await self._send(setup_message(self.model_id, self.config, resume_handle))
        self._reader = asyncio.create_task(self._read(self.connection))

    async def send_audio(self, audio: bytes) -> None:
        if self.config.turn_detection == "manual" and not self._in_activity:
            self._in_activity = True
            await self._send({"realtimeInput": {"activityStart": {}}})
        blob = {"data": base64.b64encode(audio).decode(), "mimeType": audio_mime_type(self.config.audio)}
        await self._send({"realtimeInput": {"audio": blob}})

    async def add_message(self, role: Literal["user", "assistant"], text: str) -> None:
        await self._add_turn("user" if role == "user" else "model", {"text": text})

    async def add_tool_call(self, call_id: str, name: str, arguments: str) -> None:
        self._call_names[call_id] = name
        await self._add_turn("model", {"functionCall": {"id": call_id, "name": name, "args": json.loads(arguments)}})

    async def add_tool_result(self, call_id: str, output: str) -> None:
        response = {"id": call_id, "name": self._call_names.get(call_id, ""), "response": {"output": output}}
        self._tool_answered = True
        await self._send({"toolResponse": {"functionResponses": [response]}})

    async def respond(self) -> None:
        self._responses.request()
        if self._tool_answered:
            self._tool_answered = False  # the model continues after a toolResponse by itself
        elif self._in_activity:
            self._in_activity = False
            await self._send({"realtimeInput": {"activityEnd": {}}})
        else:
            await self._send({"clientContent": {"turnComplete": True}})

    async def cancel(self) -> None:
        self._responses.cancel_current()

    async def update(self, config: VoiceConfig) -> None:
        handle = self._resume_handle
        if handle is None:
            raise GeminiNotResumable("Gemini Live offered no resumable point to apply the new config")
        await self._disconnect()
        self.config = config
        await self.connect(resume_handle=handle)

    async def events(self) -> AsyncIterator[VoiceEvent]:
        while True:
            event = await self._events.get()
            yield event
            if isinstance(event, VoiceClosed):
                return

    def response(self) -> AsyncIterator[ResponseEvent]:
        return self._responses.next_response()

    async def aclose(self) -> None:
        if self.connection is not None:
            await self.connection.close()
        if self._reader is not None:
            await self._reader

    async def _disconnect(self) -> None:
        """Drop the current connection without ending the session."""
        if self._reader is not None:
            self._reader.cancel()
            try:
                await self._reader
            except asyncio.CancelledError:
                pass
        if self.connection is not None:
            await self.connection.close()

    async def _add_turn(self, role: str, part: dict[str, Any]) -> None:
        await self._send({"clientContent": {"turns": [{"role": role, "parts": [part]}], "turnComplete": False}})

    async def _send(self, payload: dict[str, Any]) -> None:
        frame = json.dumps(payload)
        if self.observer is not None:
            self.observer("sent", frame)
        if self.connection is None:
            raise RuntimeError("the Gemini Live session is not connected")
        await self.connection.send(frame)

    async def _read(self, connection: "ClientConnection") -> None:
        from websockets.exceptions import ConnectionClosed

        try:
            async for frame in connection:
                if self.observer is not None:
                    self.observer("received", frame)
                self._handle(frame)
        except ConnectionClosed as exc:
            log.info("voice connection closed: %s", exc)
            if exc.rcvd is not None and exc.rcvd.code != 1000:
                self._events.put_nowait(VoiceError(exc.rcvd.reason or f"closed with code {exc.rcvd.code}"))
        self._responses.close()
        self._events.put_nowait(VoiceClosed())

    def _handle(self, frame: str | bytes) -> None:
        """Live sends its JSON messages as text or binary frames alike."""
        try:
            message = ServerMessage.model_validate_json(frame)
        except ValidationError as exc:
            log.warning("unreadable Gemini Live message: %s", exc)
            return
        if message.usageMetadata is not None:
            self._usage = message.usageMetadata
        if message.sessionResumptionUpdate is not None:
            update = message.sessionResumptionUpdate
            self._resume_handle = update.newHandle if update.resumable and update.newHandle else None
        if message.voiceActivity is not None:
            self._voice_activity(message.voiceActivity.type)
        if message.serverContent is not None:
            self._server_content(message.serverContent)
        if message.toolCall is not None:
            self._tool_call(message.toolCall)

    def _voice_activity(self, kind: str) -> None:
        if kind == "ACTIVITY_START":
            self._responses.utterance_started()
            self._events.put_nowait(SpeechStarted())
        elif kind == "ACTIVITY_END":
            self._responses.utterance_ended(server_answers=self.config.turn_detection == "server_vad")
            self._events.put_nowait(SpeechStopped())

    def _server_content(self, content: ServerContent) -> None:
        if content.inputTranscription is not None and content.inputTranscription.text:
            self._user_text.append(content.inputTranscription.text)
        if content.modelTurn is not None:
            turn = self._turn()
            for part in content.modelTurn.parts:
                if part.inlineData is not None and not self._responses.is_dropped(turn):
                    self._events.put_nowait(AudioDelta(base64.b64decode(part.inlineData.data)))
        if content.outputTranscription is not None and content.outputTranscription.text:
            self._responses.route(self._turn(), TextDelta(content.outputTranscription.text))
        if content.turnComplete:
            self._flush_user_text()
            self._finish_turn()

    def _tool_call(self, message: ToolCallMessage) -> None:
        turn = self._turn()
        for call in message.functionCalls:
            self._call_names[call.id] = call.name
            self._responses.route(turn, ToolCall(call.id, call.name, json.dumps(call.args)))
        self._finish_turn()

    def _turn(self) -> str:
        """The model turn in progress, starting one (and claiming it) on its first output.

        Live only generates in reply to input, so with server VAD a turn nobody requested
        answers the user's speech.
        """
        current = self._responses.current
        if current is not None:
            return current
        self._flush_user_text()
        request_id = self._responses.oldest_request()
        if request_id is None and self.config.turn_detection == "server_vad":
            self._responses.utterance_ended(server_answers=True)
        turn = f"turn-{next(self._turns)}"
        self._responses.created(turn, request_id=request_id, server_started=True)
        return turn

    def _finish_turn(self) -> None:
        usage = self._usage
        self._usage = UsageMetadata()
        done = ResponseDone(input_tokens=usage.promptTokenCount, output_tokens=usage.responseTokenCount)
        self._responses.done(self._responses.current, done)

    def _flush_user_text(self) -> None:
        if self._user_text:
            self._events.put_nowait(UserTranscript("".join(self._user_text).strip()))
            self._user_text.clear()
