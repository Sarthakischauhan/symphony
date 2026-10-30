"""AI Gateway client payloads: the normalized session config, the realtime URL and auth.

``RealtimeModelV4SessionConfig`` and the gateway's URL and subprotocols follow
https://github.com/vercel/ai (packages/provider/src/realtime-model/v4,
packages/gateway/src/gateway-realtime-model.ts and gateway-realtime-auth.ts).
"""

from typing import Any
from urllib.parse import urlencode

from core_ai.voice.session import VoiceConfig
from core_ai.voice.types import AudioFormat

AI_GATEWAY_BASE_URL = "https://ai-gateway.vercel.sh/v4/ai"
AI_GATEWAY_PROTOCOL_VERSION = "0.0.1"
REALTIME_SUBPROTOCOL = "ai-gateway-realtime.v1"
AUTH_SUBPROTOCOL_PREFIX = "ai-gateway-auth."

_AUDIO_TYPES: dict[str, str] = {
    "pcm16": "audio/pcm",
    "pcmu": "audio/pcmu",
    "pcma": "audio/pcma",
}


def audio_format(audio: AudioFormat) -> dict[str, Any]:
    return {"type": _AUDIO_TYPES[audio.encoding], "rate": audio.sample_rate}


def _tool(tool: dict[str, Any]) -> dict[str, Any]:
    """``RealtimeModelV4ToolDefinition``: a function with JSON-schema ``parameters``."""
    return {"type": "function", **tool}


def provider_options(model_id: str, effort: str) -> dict[str, Any]:
    """``providerOptions`` carrying ``effort``: the realtime docs document only Google's
    ``thinkingConfig.thinkingLevel`` (https://vercel.com/docs/ai-gateway/capabilities/realtime)."""
    owner = model_id.split("/", 1)[0]
    if owner != "google":
        raise ValueError(f"AI Gateway documents no realtime reasoning effort option for {model_id}")
    return {"google": {"thinkingConfig": {"thinkingLevel": effort.upper()}}}


def session_config(config: VoiceConfig, model_id: str) -> dict[str, Any]:
    """The ``config`` of a normalized ``session-update`` for this config and model."""
    session: dict[str, Any] = {
        "instructions": config.instructions,
        "outputModalities": ["audio"],
        "inputAudioFormat": audio_format(config.audio),
        "outputAudioFormat": audio_format(config.audio),
        "inputAudioTranscription": {},
        "outputAudioTranscription": {},
        "turnDetection": {"type": "server-vad"} if config.turn_detection == "server_vad" else None,
        "tools": [_tool(tool) for tool in config.tools],
    }
    if config.voice:
        session["voice"] = config.voice
    if config.reasoning_effort is not None:
        session["providerOptions"] = provider_options(model_id, config.reasoning_effort)
    return session


def realtime_url(base_url: str, model_id: str) -> str:
    """``wss://…/realtime-model?ai-model-id=…`` for a gateway REST base URL."""
    return f"{base_url.replace('http', 'ws', 1)}/realtime-model?{urlencode({'ai-model-id': model_id})}"


def client_secret_url(base_url: str) -> str:
    """The mint route lives at the gateway origin, not under the ``/v4/ai`` base path."""
    scheme, rest = base_url.split("://", 1)
    return f"{scheme}://{rest.split('/', 1)[0]}/v1/realtime/client-secrets"


def subprotocols(token: str) -> list[str]:
    return [REALTIME_SUBPROTOCOL, f"{AUTH_SUBPROTOCOL_PREFIX}{token}"]
