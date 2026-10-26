"""Pick a voice model from the generated catalog and open a realtime session on it."""

from typing import Optional

from core_ai.voice.catalog import VOICE_MODELS
from core_ai.voice.grok import XAI_BASE_URL, open_grok_realtime
from core_ai.voice.session import FrameObserver, VoiceConfig, VoiceSession
from core_ai.voice.types import VoiceModelSpec


def voice_model(model_id: str) -> Optional[VoiceModelSpec]:
    """The catalog model with ``provider:model`` id ``model_id``, or None."""
    return next((model for model in VOICE_MODELS if model.full_id == model_id), None)


async def open_voice_session(
    model: VoiceModelSpec,
    config: VoiceConfig,
    api_key: str,
    observer: Optional[FrameObserver] = None,
    base_url: str = XAI_BASE_URL,
) -> VoiceSession:
    """Open ``model`` with its provider's ``api_key`` (and API ``base_url``) and apply ``config``."""
    if model.provider != "grok":
        raise ValueError(f"no realtime client for voice provider {model.provider!r}")
    return await open_grok_realtime(api_key, model.id, config, observer, base_url)
