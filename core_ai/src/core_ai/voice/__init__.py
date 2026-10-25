"""Voice model calls: realtime (WebSocket), and per provider TTS and STT.

This package only talks to voice models: PCM audio in and out plus typed model events.
Tools, history and turn orchestration live with the caller.
"""

from core_ai.voice.catalog import VOICE_MODELS
from core_ai.voice.grok import GrokRealtime, GrokVoiceSession
from core_ai.voice.registry import VoiceProvider, VoiceRegistry
from core_ai.voice.types import AudioEncoding, AudioFormat, VoiceInfo, VoiceModel, VoiceModelSpec
from core_ai.voice.session import (
    AudioDelta,
    FrameDirection,
    FrameObserver,
    ResponseDone,
    ResponseEvent,
    SpeechStarted,
    SpeechStopped,
    TextDelta,
    ToolCall,
    TurnDetection,
    UserTranscript,
    VoiceClosed,
    VoiceConfig,
    VoiceError,
    VoiceEvent,
    VoiceSession,
)

__all__ = [
    "AudioEncoding",
    "AudioFormat",
    "VoiceInfo",
    "VoiceModel",
    "VoiceModelSpec",
    "AudioDelta",
    "FrameDirection",
    "FrameObserver",
    "GrokRealtime",
    "GrokVoiceSession",
    "ResponseDone",
    "ResponseEvent",
    "SpeechStarted",
    "SpeechStopped",
    "TextDelta",
    "ToolCall",
    "TurnDetection",
    "UserTranscript",
    "VOICE_MODELS",
    "VoiceClosed",
    "VoiceConfig",
    "VoiceError",
    "VoiceEvent",
    "VoiceProvider",
    "VoiceRegistry",
    "VoiceSession",
]
