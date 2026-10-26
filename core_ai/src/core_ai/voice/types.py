"""The voice package's own model types: audio formats, voices, and voice models.

Kept here rather than on core_ai's shared ``ModelInfo``: realtime models are not text models
and live only in this package's catalog.
"""

from dataclasses import dataclass
from typing import Literal

AudioEncoding = Literal["pcm16", "pcmu", "pcma"]


@dataclass(frozen=True, slots=True)
class AudioFormat:
    encoding: AudioEncoding
    sample_rate: int


@dataclass(frozen=True, slots=True)
class VoiceInfo:
    id: str
    label: str
    # Descriptive traits, where the source publishes them (Gemini's voice table does).
    traits: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VoiceSources:
    """Where a catalog entry's values were read; empty when no source publishes that value."""

    model: str
    voices: str
    reasoning_efforts: str
    audio: str


@dataclass(frozen=True, slots=True)
class VoiceModelSpec:
    """What a provider publishes about a voice model (no context window: no voice source documents one)."""

    id: str
    provider: str
    voices: tuple[VoiceInfo, ...]
    default_voice: str
    audio_input: tuple[AudioFormat, ...]
    audio_output: tuple[AudioFormat, ...]
    # Provider-native reasoning effort values, lowest first.
    reasoning_efforts: tuple[str, ...] = ()
    sources: VoiceSources | None = None

    @property
    def full_id(self) -> str:
        return f"{self.provider}:{self.id}"
