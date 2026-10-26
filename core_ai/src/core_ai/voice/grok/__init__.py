"""xAI voice models. ``realtime`` is the speech-to-speech WebSocket; TTS and STT clients
belong beside it as ``tts.py`` and ``stt.py`` when a caller needs them."""

from core_ai.voice.grok.realtime import XAI_BASE_URL, GrokVoiceSession, open_grok_realtime, realtime_url

__all__ = ["XAI_BASE_URL", "GrokVoiceSession", "open_grok_realtime", "realtime_url"]
