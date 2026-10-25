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
    traits: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VoiceModelSpec:
    """What a provider publishes about a voice model (no context window: xAI documents none)."""

    id: str
    provider: str
    voices: tuple[VoiceInfo, ...]
    default_voice: str
    audio_input: tuple[AudioFormat, ...]
    audio_output: tuple[AudioFormat, ...]
    # Provider-native reasoning effort values, lowest first.
    reasoning_efforts: tuple[str, ...] = ()

    @property
    def full_id(self) -> str:
        return f"{self.provider}:{self.id}"


@dataclass(frozen=True, slots=True)
class VoiceModel:
    """A voice model as a ``VoiceRegistry`` serves it: its spec plus the required, configured
    context window in tokens."""

    spec: VoiceModelSpec
    context_limit: int

    @property
    def full_id(self) -> str:
        return self.spec.full_id
