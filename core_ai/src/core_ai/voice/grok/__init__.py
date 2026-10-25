"""xAI voice models. ``realtime`` is the speech-to-speech WebSocket; TTS and STT clients
belong beside it as ``tts.py`` and ``stt.py`` when a caller needs them."""

from core_ai.voice.grok.realtime import GrokRealtime, GrokVoiceSession, realtime_url

__all__ = ["GrokRealtime", "GrokVoiceSession", "realtime_url"]
