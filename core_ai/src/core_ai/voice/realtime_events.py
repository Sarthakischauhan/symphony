"""Server events of the OpenAI-style realtime protocol, as typed models.

xAI and OpenAI share these names and fields: the xAI Voice API reference,
https://docs.x.ai/developers/rest-api-reference/inference/voice (server events), and
OpenAI's published spec, https://github.com/openai/openai-openapi (``RealtimeServerEvent*``).
Deltas, function calls and output items carry ``response_id``; ``response.created`` and
``response.done`` carry the response object, whose ``metadata`` echoes what the client sent
with ``response.create`` and is null for responses the server starts itself (server VAD).
xAI's binary audio frames are raw PCM with no envelope (binary transport,
https://docs.x.ai/developers/model-capabilities/audio/voice-agent), so they belong to the
response in progress.
"""

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class Incoming(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Envelope(Incoming):
    type: str


class SpeechStartedEvent(Incoming):
    type: Literal["input_audio_buffer.speech_started"]


class SpeechStoppedEvent(Incoming):
    type: Literal["input_audio_buffer.speech_stopped"]


class TranscriptionCompleted(Incoming):
    type: Literal["conversation.item.input_audio_transcription.completed"]
    transcript: str = ""


class RequestMetadata(Incoming):
    request_id: Optional[str] = None


class CreatedResponse(Incoming):
    id: str
    metadata: Optional[RequestMetadata] = None


class ResponseCreated(Incoming):
    type: Literal["response.created"]
    response: CreatedResponse


class TranscriptDelta(Incoming):
    type: Literal["response.output_audio_transcript.delta"]
    response_id: Optional[str] = None
    delta: str


class AudioDeltaEvent(Incoming):
    type: Literal["response.output_audio.delta"]
    response_id: Optional[str] = None
    delta: str


class FunctionCallDone(Incoming):
    type: Literal["response.function_call_arguments.done"]
    response_id: Optional[str] = None
    call_id: str
    name: str
    arguments: str


class OutputItem(Incoming):
    type: str
    call_id: Optional[str] = None
    name: Optional[str] = None
    arguments: Optional[str] = None


class OutputItemDone(Incoming):
    type: Literal["response.output_item.done"]
    response_id: Optional[str] = None
    item: OutputItem


class Usage(Incoming):
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


class StatusDetails(Incoming):
    reason: Optional[str] = None


class DoneResponse(Incoming):
    id: Optional[str] = None
    status: Optional[str] = None
    status_details: Optional[StatusDetails] = None
    usage: Optional[Usage] = None


class ResponseDoneEvent(Incoming):
    type: Literal["response.done"]
    response: DoneResponse = DoneResponse()


class ErrorDetail(Incoming):
    message: str = "unknown error"


class ErrorEvent(Incoming):
    type: Literal["error"]
    error: ErrorDetail = ErrorDetail()


ServerEvent = Annotated[
    Union[
        SpeechStartedEvent,
        SpeechStoppedEvent,
        TranscriptionCompleted,
        ResponseCreated,
        TranscriptDelta,
        AudioDeltaEvent,
        FunctionCallDone,
        OutputItemDone,
        ResponseDoneEvent,
        ErrorEvent,
    ],
    Field(discriminator="type"),
]
server_event: TypeAdapter[ServerEvent] = TypeAdapter(ServerEvent)
HANDLED = frozenset(
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
