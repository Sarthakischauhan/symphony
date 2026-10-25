"""A provider-neutral realtime voice session.

A session carries two streams. ``events()`` is the audio side a voice front end consumes:
speech boundaries, what the user said, and the assistant's audio. ``response()`` is the model
side: the text and tool calls of one assistant response, which ``VoiceModelCall`` turns into
``StreamEvent``s so a harness run can own the turn.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Optional, Union

from core_ai.models.types import AudioFormat

TurnDetection = Literal["server_vad", "manual"]
FrameDirection = Literal["sent", "received"]
FrameObserver = Callable[[FrameDirection, Union[str, bytes]], None]


@dataclass(frozen=True, slots=True)
class VoiceConfig:
    voice: str
    instructions: str = ""
    tools: tuple[dict[str, Any], ...] = ()
    reasoning_effort: Optional[str] = None
    audio: AudioFormat = AudioFormat("pcm16", 24000)
    turn_detection: TurnDetection = "server_vad"


@dataclass(frozen=True, slots=True)
class SpeechStarted:
    type: Literal["speech_started"] = "speech_started"


@dataclass(frozen=True, slots=True)
class SpeechStopped:
    type: Literal["speech_stopped"] = "speech_stopped"


@dataclass(frozen=True, slots=True)
class UserTranscript:
    text: str
    type: Literal["user_transcript"] = "user_transcript"


@dataclass(frozen=True, slots=True)
class AudioDelta:
    audio: bytes
    type: Literal["audio_delta"] = "audio_delta"


@dataclass(frozen=True, slots=True)
class VoiceError:
    message: str
    type: Literal["error"] = "error"


@dataclass(frozen=True, slots=True)
class VoiceClosed:
    type: Literal["closed"] = "closed"


VoiceEvent = Union[
    SpeechStarted, SpeechStopped, UserTranscript, AudioDelta, VoiceError, VoiceClosed
]


@dataclass(frozen=True, slots=True)
class TextDelta:
    text: str
    type: Literal["text_delta"] = "text_delta"


@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    name: str
    arguments: str
    type: Literal["tool_call"] = "tool_call"


@dataclass(frozen=True, slots=True)
class ResponseDone:
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    error: Optional[str] = None
    type: Literal["response_done"] = "response_done"


ResponseEvent = Union[TextDelta, ToolCall, ResponseDone]


@dataclass(slots=True)
class VoiceHistory:
    """What the session has already been told, so a model call only sends what is new."""

    synced: bool = False
    heard: list[str] = field(default_factory=list)


class VoiceSession(ABC):
    """One live realtime connection. Close it with ``aclose`` (or ``ModelRegistry.close_voice``)."""

    model_id: str
    config: VoiceConfig
    history: VoiceHistory

    @abstractmethod
    async def send_audio(self, audio: bytes) -> None:
        """Append caller audio (in ``config.audio`` format) to the input buffer."""

    @abstractmethod
    async def add_message(self, role: Literal["user", "assistant"], text: str) -> None:
        """Add a text message to the conversation without asking for a response."""

    @abstractmethod
    async def add_tool_result(self, call_id: str, output: str) -> None:
        """Answer a tool call without asking for a response."""

    @abstractmethod
    async def respond(self) -> None:
        """Ask the model for a response to the conversation so far."""

    @abstractmethod
    async def cancel(self) -> None:
        """Stop the response in flight; its remaining events are dropped."""

    @abstractmethod
    async def update(self, config: VoiceConfig) -> None:
        """Replace the session configuration (voice, instructions, tools, effort)."""

    @abstractmethod
    def events(self) -> AsyncIterator[VoiceEvent]:
        """Audio-side events until the session closes (ending with ``VoiceClosed``)."""

    @abstractmethod
    def response(self) -> AsyncIterator[ResponseEvent]:
        """The next response's events, ending with its ``ResponseDone``."""

    @abstractmethod
    async def aclose(self) -> None:
        """Close the connection."""
