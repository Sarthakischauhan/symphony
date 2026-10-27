"""Pick a voice model from the generated catalog and open a realtime session on it."""

from collections.abc import Awaitable, Callable
from typing import Optional

from core_ai.voice.catalog import VOICE_MODELS
from core_ai.voice.gemini import GEMINI_LIVE_URL, open_gemini_live
from core_ai.voice.grok import XAI_BASE_URL, open_grok_realtime
from core_ai.voice.openai import OPENAI_BASE_URL, open_openai_realtime
from core_ai.voice.sarvam import SARVAM_BASE_URL, open_sarvam_realtime
from core_ai.voice.session import FrameObserver, VoiceConfig, VoiceSession
from core_ai.voice.types import VoiceModelSpec
from core_ai.voice.vercel import AI_GATEWAY_BASE_URL, open_vercel_realtime

RealtimeOpener = Callable[[str, str, VoiceConfig, Optional[FrameObserver], str], Awaitable[VoiceSession]]

# Catalog provider -> (realtime client, its default API base URL).
REALTIME_CLIENTS: dict[str, tuple[RealtimeOpener, str]] = {
    "grok": (open_grok_realtime, XAI_BASE_URL),
    "openai": (open_openai_realtime, OPENAI_BASE_URL),
    "gemini": (open_gemini_live, GEMINI_LIVE_URL),
    "vercel": (open_vercel_realtime, AI_GATEWAY_BASE_URL),
    "sarvam": (open_sarvam_realtime, SARVAM_BASE_URL),
}


def voice_model(model_id: str) -> Optional[VoiceModelSpec]:
    """The catalog model with ``provider:model`` id ``model_id``, or None."""
    return next((model for model in VOICE_MODELS if model.full_id == model_id), None)


async def open_voice_session(
    model: VoiceModelSpec,
    config: VoiceConfig,
    api_key: str,
    observer: Optional[FrameObserver] = None,
    base_url: Optional[str] = None,
) -> VoiceSession:
    """Open ``model`` with its provider's ``api_key`` and apply ``config``; ``base_url``
    overrides the provider's default API (or, for Gemini, Live WebSocket) URL."""
    client = REALTIME_CLIENTS.get(model.provider)
    if client is None:
        raise ValueError(f"no realtime client for voice provider {model.provider!r}")
    opener, default_url = client
    return await opener(api_key, model.id, config, observer, base_url or default_url)
