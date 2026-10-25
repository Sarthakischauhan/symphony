"""Voice model calls: realtime (WebSocket), and per provider TTS and STT.

This package only talks to voice models: PCM audio in and out plus typed model events.
Tools, history and turn orchestration live with the caller (core_harness, the host app).
"""

from core_ai.voice.catalog import VOICE_MODELS, voice_catalog
from core_ai.voice.grok import GrokRealtime, GrokVoiceSession
from core_ai.voice.registry import MissingVoiceContextLimit, VoiceProvider, VoiceRegistry
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
    "AudioDelta",
    "FrameDirection",
    "FrameObserver",
    "GrokRealtime",
    "GrokVoiceSession",
    "MissingVoiceContextLimit",
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
    "voice_catalog",
]
