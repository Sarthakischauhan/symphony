from dataclasses import dataclass
from typing import Literal

ModelAPI = Literal[
    "responses", "chat_completions", "messages", "generate_content", "realtime"
]
ThinkingLevel = Literal["off", "minimal", "low", "medium", "high", "xhigh", "max"]
ThinkingLevelMap = tuple[tuple[ThinkingLevel, str | None], ...]
Modality = Literal["text", "audio"]
AudioEncoding = Literal["pcm16", "pcmu", "pcma"]


@dataclass(frozen=True, slots=True)
class AudioFormat:
    encoding: AudioEncoding
    sample_rate: int


@dataclass(frozen=True, slots=True)
class VoiceInfo:
    id: str
    label: str
    traits: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ModelInfo:
    id: str
    provider: str
    api: ModelAPI
    reasoning: bool = False
    thinking_level_map: ThinkingLevelMap = ()
    context_limit: int | None = None
    input_modalities: tuple[Modality, ...] = ("text",)
    output_modalities: tuple[Modality, ...] = ("text",)
    audio_input: tuple[AudioFormat, ...] = ()
    audio_output: tuple[AudioFormat, ...] = ()
    voices: tuple[VoiceInfo, ...] = ()
    default_voice: str | None = None

    @property
    def full_id(self) -> str:
        return f"{self.provider}:{self.id}"

    @property
    def reasoning_efforts(self) -> tuple[str, ...]:
        """Provider-native reasoning effort values, in thinking-level order."""
        return tuple(native for _level, native in self.thinking_level_map if native)
