"""Voice model calls: realtime (WebSocket), and per provider TTS and STT.

This package only talks to voice models: PCM audio in and out plus typed model events.
Tools, history and turn orchestration live with the caller.
"""

from core_ai.voice.catalog import VOICE_MODELS
from core_ai.voice.grok import GrokVoiceSession
from core_ai.voice.models import open_voice_session, voice_model
from core_ai.voice.types import AudioEncoding, AudioFormat, VoiceInfo, VoiceModelSpec
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
    "VoiceModelSpec",
    "AudioDelta",
    "FrameDirection",
    "FrameObserver",
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
    "VoiceSession",
    "open_voice_session",
    "voice_model",
]
