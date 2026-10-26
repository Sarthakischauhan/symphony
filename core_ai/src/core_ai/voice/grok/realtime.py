"""xAI speech-to-speech sessions over ``wss://api.x.ai/v1/realtime``.

Event names follow https://docs.x.ai/developers/rest-api-reference/inference/voice. Audio goes
both ways as binary frames (binary transport); everything else is JSON.
"""

from typing import Any, Optional

from core_ai.voice.grok.payload import session_payload
from core_ai.voice.realtime_api import RealtimeApiSession, realtime_url
from core_ai.voice.session import FrameObserver, VoiceConfig

XAI_BASE_URL = "https://api.x.ai/v1"


async def open_grok_realtime(
    api_key: str,
    model_name: str,
    config: VoiceConfig,
    observer: Optional[FrameObserver] = None,
    base_url: str = XAI_BASE_URL,
) -> "GrokVoiceSession":
    """Connect to xAI realtime model ``model_name`` on an xAI account's key and apply ``config``."""
    return await GrokVoiceSession.open(realtime_url(base_url), api_key, model_name, config, observer)


class GrokVoiceSession(RealtimeApiSession):
    """One xAI realtime connection; input audio goes as raw binary frames."""

    def session_payload(self, config: VoiceConfig) -> dict[str, Any]:
        return session_payload(config)

    async def send_audio(self, audio: bytes) -> None:
        self._observe_sent(audio)
        await self.connection.send(audio)
