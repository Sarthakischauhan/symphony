"""Client payloads: the ``session`` of a ``session.update`` and the realtime URL."""

from typing import Any

from core_ai.voice.types import AudioFormat
from core_ai.voice.session import VoiceConfig

_AUDIO_TYPES: dict[str, str] = {
    "pcm16": "audio/pcm",
    "pcmu": "audio/pcmu",
    "pcma": "audio/pcma",
}


def _audio_config(audio: AudioFormat) -> dict[str, Any]:
    direction = {
        "format": {"type": _AUDIO_TYPES[audio.encoding], "rate": audio.sample_rate},
        "transport": "binary",
    }
    return {"input": direction, "output": direction}


def session_payload(config: VoiceConfig) -> dict[str, Any]:
    """The ``session`` object of a ``session.update`` for this config."""
    session: dict[str, Any] = {
        "voice": config.voice,
        "instructions": config.instructions,
        "turn_detection": {"type": "server_vad"} if config.turn_detection == "server_vad" else None,
        "audio": _audio_config(config.audio),
        "tools": [{"type": "function", **tool} for tool in config.tools],
    }
    if config.reasoning_effort is not None:
        session["reasoning"] = {"effort": config.reasoning_effort}
    return session


def realtime_url(base_url: str) -> str:
    """``wss://…/realtime`` on the same host as an xAI REST base URL."""
    scheme, rest = base_url.split("://", 1)
    return f"{'wss' if scheme == 'https' else 'ws'}://{rest}/realtime"
