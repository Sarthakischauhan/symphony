"""Sarvam realtime speech-to-text over ``wss://api.sarvam.ai/speech-to-text-realtime/ws``.

Per Sarvam's AsyncAPI spec (https://docs.sarvam.ai/asyncapi.json), the channel takes its
configuration as query parameters, authenticates with the ``api-subscription-key`` header,
accepts base64 ``audio_input`` messages and answers with VAD events and transcripts. It is
transcription only: Sarvam documents no realtime model that responds, so there is no
response, history or tool call to send, and those calls raise ``SarvamResponsesUnsupported``.
"""

import asyncio
import base64
import json
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, Literal, Optional
from urllib.parse import urlencode

from core_ai.voice.session import (
    FrameObserver,
    ResponseEvent,
    SpeechStarted,
    SpeechStopped,
    UserTranscript,
    VoiceClosed,
    VoiceConfig,
    VoiceError,
    VoiceEvent,
    VoiceSession,
)
from core_ai.voice.types import AudioEncoding

if TYPE_CHECKING:
    from websockets.asyncio.client import ClientConnection

log = logging.getLogger(__name__)

SARVAM_BASE_URL = "https://api.sarvam.ai"
REALTIME_PATH = "/speech-to-text-realtime/ws"
# ``language_code`` is required; ``auto`` is its documented adaptive language detection.
AUTO_LANGUAGE = "auto"
# The channel's ``encoding`` values for the encodings core_ai's sessions carry.
ENCODINGS: dict[AudioEncoding, str] = {"pcm16": "linear16", "pcmu": "mulaw", "pcma": "alaw"}
ENDPOINTING = {"server_vad": "vad", "manual": "manual"}


class SarvamResponsesUnsupported(ValueError):
    """Sarvam's realtime channel transcribes; it has no model response, history or tools."""


def realtime_url(base_url: str, model_id: str, config: VoiceConfig) -> str:
    scheme, rest = base_url.split("://", 1)
    query = {
        "model": model_id,
        "language_code": config.language or AUTO_LANGUAGE,
        "encoding": ENCODINGS[config.audio.encoding],
        "sample_rate": str(config.audio.sample_rate),
        "endpointing": ENDPOINTING[config.turn_detection],
    }
    return f"{'wss' if scheme == 'https' else 'ws'}://{rest}{REALTIME_PATH}?{urlencode(query)}"


async def open_sarvam_realtime(
    api_key: str,
    model_name: str,
    config: VoiceConfig,
    observer: Optional[FrameObserver] = None,
    base_url: str = SARVAM_BASE_URL,
) -> "SarvamVoiceSession":
    """Connect realtime STT model ``model_name`` with ``config``'s audio format and language."""
    from websockets.asyncio.client import connect

    connection = await connect(
        realtime_url(base_url, model_name, config),
        additional_headers={"api-subscription-key": api_key},
        max_size=None,
    )
    session = SarvamVoiceSession(connection, model_name, config, observer)
    session.start()
    return session


class SarvamVoiceSession(VoiceSession):
    """One realtime STT connection: audio in, speech events and final transcripts out.

    With ``turn_detection="manual"`` the first audio of a turn sends ``speech_start`` and
    ``respond()`` sends ``speech_end``, which makes the server finalize that turn's transcript.
    """

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
        self._in_turn = False
        self._reader: Optional[asyncio.Task[None]] = None

    def start(self) -> None:
        self._reader = asyncio.create_task(self._read())

    async def send_audio(self, audio: bytes) -> None:
        if self.config.turn_detection == "manual" and not self._in_turn:
            self._in_turn = True
            await self._send({"event": "speech_start"})
        await self._send({"event": "audio_input", "audio": base64.b64encode(audio).decode()})

    async def add_message(self, role: Literal["user", "assistant"], text: str) -> None:
        raise SarvamResponsesUnsupported("Sarvam realtime speech-to-text keeps no conversation history")

    async def add_tool_call(self, call_id: str, name: str, arguments: str) -> None:
        raise SarvamResponsesUnsupported("Sarvam realtime speech-to-text has no tool calls")

    async def add_tool_result(self, call_id: str, output: str) -> None:
        raise SarvamResponsesUnsupported("Sarvam realtime speech-to-text has no tool calls")

    async def respond(self) -> None:
        """Ends a manual turn (``speech_end``); server VAD ends turns itself."""
        if self.config.turn_detection != "manual":
            raise SarvamResponsesUnsupported("Sarvam realtime speech-to-text has no model response")
        self._in_turn = False
        await self._send({"event": "speech_end"})

    async def cancel(self) -> None:
        raise SarvamResponsesUnsupported("Sarvam realtime speech-to-text has no model response")

    async def update(self, config: VoiceConfig) -> None:
        """Re-arms ``language_code`` with ``config.update``; the rest is fixed at connect."""
        if (config.audio, config.turn_detection) != (self.config.audio, self.config.turn_detection):
            raise SarvamResponsesUnsupported("Sarvam sets audio format and endpointing only when connecting")
        self.config = config
        await self._send({"event": "config.update", "language_code": config.language or AUTO_LANGUAGE})

    async def events(self) -> AsyncIterator[VoiceEvent]:
        while True:
            event = await self._events.get()
            yield event
            if isinstance(event, VoiceClosed):
                return

    def response(self) -> AsyncIterator[ResponseEvent]:
        raise SarvamResponsesUnsupported("Sarvam realtime speech-to-text has no model response")

    async def aclose(self) -> None:
        await self.connection.close()
        if self._reader is not None:
            await self._reader

    async def _send(self, payload: dict[str, Any]) -> None:
        frame = json.dumps(payload)
        if self.observer is not None:
            self.observer("sent", frame)
        await self.connection.send(frame)

    async def _read(self) -> None:
        from websockets.exceptions import ConnectionClosed

        try:
            async for frame in self.connection:
                if self.observer is not None:
                    self.observer("received", frame)
                self._handle(json.loads(frame))
        except ConnectionClosed as exc:
            log.info("voice connection closed: %s", exc)
        finally:
            self._events.put_nowait(VoiceClosed())

    def _handle(self, message: dict[str, Any]) -> None:
        event = message.get("event")
        if event == "vad.speech_start":
            self._events.put_nowait(SpeechStarted())
        elif event == "vad.speech_end":
            self._events.put_nowait(SpeechStopped())
        elif event == "transcript.final":
            self._events.put_nowait(UserTranscript(message["text"].strip()))
        elif event == "error":
            self._events.put_nowait(VoiceError(message.get("message") or message.get("code") or "error"))
