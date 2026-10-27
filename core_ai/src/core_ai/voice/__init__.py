"""Voice model calls: realtime (WebSocket), and per provider TTS and STT.

Providers: ``grok`` (xAI), ``openai``, ``gemini`` (Gemini Live), ``vercel`` (AI Gateway)
and ``sarvam`` (Sarvam AI realtime speech-to-text; its TTS and STT models are in ``SPEECH_MODELS``).

This package only talks to voice models: PCM audio in and out plus typed model events.
Tools, history and turn orchestration live with the caller.
"""

from core_ai.voice.catalog import SPEECH_MODELS, VOICE_MODELS
from core_ai.voice.gemini import GeminiVoiceSession
from core_ai.voice.grok import GrokVoiceSession
from core_ai.voice.models import open_voice_session, voice_model
from core_ai.voice.openai import OpenAIVoiceSession
from core_ai.voice.sarvam import SarvamResponsesUnsupported, SarvamVoiceSession
from core_ai.voice.types import (
    AudioEncoding,
    AudioFormat,
    SpeechKind,
    SpeechModelSpec,
    SpeechSources,
    VoiceInfo,
    VoiceModelSpec,
    VoiceSources,
)
from core_ai.voice.vercel import VercelVoiceSession
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
    "VoiceSources",
    "SPEECH_MODELS",
    "SarvamResponsesUnsupported",
    "SarvamVoiceSession",
    "SpeechKind",
    "SpeechModelSpec",
    "SpeechSources",
    "AudioDelta",
    "FrameDirection",
    "FrameObserver",
    "GeminiVoiceSession",
    "GrokVoiceSession",
    "OpenAIVoiceSession",
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
    "VercelVoiceSession",
    "open_voice_session",
    "voice_model",
]
