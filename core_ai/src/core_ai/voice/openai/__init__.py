"""OpenAI voice models: the realtime speech-to-speech WebSocket, plus TTS and STT."""

from core_ai.voice.openai.realtime import OPENAI_BASE_URL, OpenAIVoiceSession, open_openai_realtime
from core_ai.voice.openai.speech import synthesize, transcribe

__all__ = ["OPENAI_BASE_URL", "OpenAIVoiceSession", "open_openai_realtime", "synthesize", "transcribe"]
