"""AI Gateway speech-to-speech sessions over ``wss://ai-gateway.vercel.sh/v4/ai/realtime-model``.

The gateway speaks the AI SDK's normalized realtime protocol (``events``, ``payload``) for every
upstream model. A long-lived gateway API key mints a short-lived client secret
(``POST /v1/realtime/client-secrets``), which authenticates the WebSocket as the
``ai-gateway-auth.<token>`` subprotocol. Normalized conversation items are user text, user
audio and tool outputs only (``RealtimeModelV4ConversationItem``), so assistant messages and
earlier tool calls cannot be replayed into a gateway session.
"""

import asyncio
import base64
import json
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, Literal, Optional

import httpx
from pydantic import ValidationError

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
from core_ai.voice.vercel.events import (
    HANDLED,
    AudioDeltaEvent,
    Envelope,
    FunctionCallDone,
    ResponseCreated,
    ResponseDoneEvent,
    SpeechStartedEvent,
    SpeechStoppedEvent,
    TranscriptDelta,
    TranscriptionCompleted,
    server_event,
)
from core_ai.voice.vercel.payload import (
    AI_GATEWAY_BASE_URL,
    AI_GATEWAY_PROTOCOL_VERSION,
    client_secret_url,
    realtime_url,
    session_config,
    subprotocols,
)

if TYPE_CHECKING:
    from websockets.asyncio.client import ClientConnection

log = logging.getLogger(__name__)


class GatewayHistoryUnsupported(ValueError):
    """The normalized protocol has no conversation item for this kind of history."""


def gateway_headers(api_key: str) -> dict[str, str]:
    """REST auth for a gateway API key (``createAuthHeaders`` in packages/gateway)."""
    return {
        "Authorization": f"Bearer {api_key}",
        "ai-gateway-protocol-version": AI_GATEWAY_PROTOCOL_VERSION,
        "ai-gateway-auth-method": "api-key",
    }


async def mint_client_secret(api_key: str, model_id: str, base_url: str = AI_GATEWAY_BASE_URL) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            client_secret_url(base_url), headers=gateway_headers(api_key), json={"model": model_id}
        )
    response.raise_for_status()
    token: str = response.json()["token"]
    return token


async def open_vercel_realtime(
    api_key: str,
    model_name: str,
    config: VoiceConfig,
    observer: Optional[FrameObserver] = None,
    base_url: str = AI_GATEWAY_BASE_URL,
) -> "VercelVoiceSession":
    """Connect to gateway realtime model ``model_name`` (``owner/model``) and apply ``config``."""
    from websockets.asyncio.client import connect
    from websockets.typing import Subprotocol

    token = await mint_client_secret(api_key, model_name, base_url)
    connection = await connect(
        realtime_url(base_url, model_name),
        subprotocols=[Subprotocol(protocol) for protocol in subprotocols(token)],
        max_size=None,
    )
    session = VercelVoiceSession(connection, model_name, config, observer)
    await session._send({"type": "session-update", "config": session_config(config)})
    session.start()
    return session


class VercelVoiceSession(VoiceSession):
    """One AI Gateway realtime connection. ``response()`` yields only requested responses."""

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
        self._call_names: dict[str, str] = {}
        self._reader: Optional[asyncio.Task[None]] = None

    def start(self) -> None:
        self._reader = asyncio.create_task(self._read())

    async def send_audio(self, audio: bytes) -> None:
        await self._send({"type": "input-audio-append", "audio": base64.b64encode(audio).decode()})

    async def add_message(self, role: Literal["user", "assistant"], text: str) -> None:
        if role != "user":
            raise GatewayHistoryUnsupported("AI Gateway realtime conversation items are user messages only")
        await self._add_item({"type": "text-message", "role": "user", "text": text})

    async def add_tool_call(self, call_id: str, name: str, arguments: str) -> None:
        raise GatewayHistoryUnsupported("AI Gateway realtime cannot replay an earlier tool call")

    async def add_tool_result(self, call_id: str, output: str) -> None:
        item: dict[str, Any] = {"type": "function-call-output", "callId": call_id, "output": output}
        name = self._call_names.get(call_id)
        if name is not None:
            item["name"] = name
        await self._add_item(item)

    async def respond(self) -> None:
        self._responses.request()
        await self._send({"type": "response-create"})

    async def cancel(self) -> None:
        if self._responses.cancel_current():
            await self._send({"type": "response-cancel"})

    async def update(self, config: VoiceConfig) -> None:
        self.config = config
        await self._send({"type": "session-update", "config": session_config(config)})

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
        await self._send({"type": "conversation-item-create", "item": item})

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
                self._handle(frame)
        except ConnectionClosed as exc:
            log.info("voice connection closed: %s", exc)
        finally:
            self._responses.close()
            self._events.put_nowait(VoiceClosed())

    def _handle(self, frame: str | bytes) -> None:
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
            self._responses.created(event.responseId, request_id=self._responses.oldest_request(), server_started=True)
        elif isinstance(event, TranscriptDelta):
            self._responses.route(event.responseId, TextDelta(event.delta))
        elif isinstance(event, AudioDeltaEvent):
            if not self._responses.is_dropped(event.responseId):
                self._events.put_nowait(AudioDelta(base64.b64decode(event.delta)))
        elif isinstance(event, FunctionCallDone):
            self._call_names[event.callId] = event.name
            self._responses.route(event.responseId, ToolCall(event.callId, event.name, event.arguments))
        elif isinstance(event, ResponseDoneEvent):
            failed = event.status == "failed"
            self._responses.done(event.responseId, ResponseDone(error=event.status if failed else None))
        else:
            self._events.put_nowait(VoiceError(event.message))
