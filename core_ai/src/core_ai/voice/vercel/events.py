"""The AI Gateway realtime server events this client reads, as typed models.

AI Gateway speaks the AI SDK's normalized realtime protocol and translates it to the upstream
provider (``GatewayRealtimeModel`` in https://github.com/vercel/ai, packages/gateway); the
events are ``RealtimeModelV4ServerEvent`` in packages/provider/src/realtime-model/v4. The
normalized ``response-created`` carries no request metadata, so requested responses are
matched in request order.
"""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class Incoming(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Envelope(Incoming):
    type: str


class SpeechStartedEvent(Incoming):
    type: Literal["speech-started"]


class SpeechStoppedEvent(Incoming):
    type: Literal["speech-stopped"]


class TranscriptionCompleted(Incoming):
    type: Literal["input-transcription-completed"]
    transcript: str = ""


class ResponseCreated(Incoming):
    type: Literal["response-created"]
    responseId: str


class AudioDeltaEvent(Incoming):
    type: Literal["audio-delta"]
    responseId: str
    delta: str


class TranscriptDelta(Incoming):
    type: Literal["audio-transcript-delta"]
    responseId: str
    delta: str


class FunctionCallDone(Incoming):
    type: Literal["function-call-arguments-done"]
    responseId: str
    callId: str
    name: str
    arguments: str


class ResponseDoneEvent(Incoming):
    type: Literal["response-done"]
    responseId: str
    status: str


class ErrorEvent(Incoming):
    type: Literal["error"]
    message: str = "unknown error"


ServerEvent = Annotated[
    Union[
        SpeechStartedEvent,
        SpeechStoppedEvent,
        TranscriptionCompleted,
        ResponseCreated,
        AudioDeltaEvent,
        TranscriptDelta,
        FunctionCallDone,
        ResponseDoneEvent,
        ErrorEvent,
    ],
    Field(discriminator="type"),
]
server_event: TypeAdapter[ServerEvent] = TypeAdapter(ServerEvent)
HANDLED = frozenset(
    {
        "speech-started",
        "speech-stopped",
        "input-transcription-completed",
        "response-created",
        "audio-delta",
        "audio-transcript-delta",
        "function-call-arguments-done",
        "response-done",
        "error",
    }
)
