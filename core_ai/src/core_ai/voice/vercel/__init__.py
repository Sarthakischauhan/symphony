"""Vercel AI Gateway voice models: the normalized realtime WebSocket, plus TTS and STT."""

from core_ai.voice.vercel.payload import AI_GATEWAY_BASE_URL
from core_ai.voice.vercel.realtime import GatewayHistoryUnsupported, VercelVoiceSession, open_vercel_realtime
from core_ai.voice.vercel.speech import synthesize, transcribe

__all__ = [
    "AI_GATEWAY_BASE_URL",
    "GatewayHistoryUnsupported",
    "VercelVoiceSession",
    "open_vercel_realtime",
    "synthesize",
    "transcribe",
]
