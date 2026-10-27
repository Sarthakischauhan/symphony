"""A provider-neutral realtime voice session.

The contract is PCM audio in and out plus typed events. ``events()`` yields speech boundaries,
what the user said, and the assistant's audio; ``response()`` yields the text and tool calls of
one assistant response. The caller owns turns and history: it decides when to respond, runs
tools, and replays prior history into the session.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Literal, Optional, Union

from core_ai.voice.types import AudioFormat

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
    # Input language code, for models that take one (Sarvam's realtime STT); None lets the
    # model choose.
    language: Optional[str] = None


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


VoiceEvent = Union[SpeechStarted, SpeechStopped, UserTranscript, AudioDelta, VoiceError, VoiceClosed]


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


class VoiceSession(ABC):
    """One live realtime connection: PCM audio in and out, plus typed model events.

    Close it with ``aclose``. Conversation history and turn ownership belong to the caller.
    """

    model_id: str
    config: VoiceConfig

    @abstractmethod
    async def send_audio(self, audio: bytes) -> None:
        """Append caller audio (in ``config.audio`` format) to the input buffer."""

    @abstractmethod
    async def add_message(self, role: Literal["user", "assistant"], text: str) -> None:
        """Add a text message to the conversation without asking for a response."""

    @abstractmethod
    async def add_tool_call(self, call_id: str, name: str, arguments: str) -> None:
        """Seed a tool call the assistant made earlier (history replay), without a response."""

    @abstractmethod
    async def add_tool_result(self, call_id: str, output: str) -> None:
        """Answer a tool call without asking for a response."""

    @abstractmethod
    async def respond(self) -> None:
        """Ask the model for a response to the conversation so far.

        Only requested responses reach ``response()``: one asked for here, or, with server VAD,
        one the server starts for committed speech. Any other response is dropped.
        """

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
        """The next requested response's events, ending with its ``ResponseDone``."""

    @abstractmethod
    async def aclose(self) -> None:
        """Close the connection."""
