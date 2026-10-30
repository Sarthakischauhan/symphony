"""OpenAI speech-to-speech sessions over ``wss://api.openai.com/v1/realtime``.

The protocol is the one xAI shares (``core_ai.voice.realtime_api``); OpenAI's differences are
the ``session`` shape (``payload``) and input audio, which goes base64 in
``input_audio_buffer.append`` (there is no binary transport).
"""

import base64
from typing import Any, Optional

from core_ai.voice.openai.payload import session_payload
from core_ai.voice.realtime_api import RealtimeApiSession, realtime_url
from core_ai.voice.session import FrameObserver, VoiceConfig

OPENAI_BASE_URL = "https://api.openai.com/v1"


async def open_openai_realtime(
    api_key: str,
    model_name: str,
    config: VoiceConfig,
    observer: Optional[FrameObserver] = None,
    base_url: str = OPENAI_BASE_URL,
) -> "OpenAIVoiceSession":
    """Connect to OpenAI realtime model ``model_name`` with an OpenAI key and apply ``config``."""
    return await OpenAIVoiceSession.open(realtime_url(base_url), api_key, model_name, config, observer)


class OpenAIVoiceSession(RealtimeApiSession):
    """One OpenAI realtime connection."""

    def session_payload(self, config: VoiceConfig) -> dict[str, Any]:
        return session_payload(config)

    async def send_audio(self, audio: bytes) -> None:
        await self._send({"type": "input_audio_buffer.append", "audio": base64.b64encode(audio).decode()})
