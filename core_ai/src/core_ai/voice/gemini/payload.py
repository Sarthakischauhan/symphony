"""Gemini Live client messages: ``setup`` and the WebSocket URL (https://ai.google.dev/api/live).

Live audio is raw little-endian PCM16; input carries its rate in the Blob MIME type
(``audio/pcm;rate=16000``) and output is always 24 kHz
(https://ai.google.dev/gemini-api/docs/live-api/capabilities).
"""

from typing import Any, Optional
from urllib.parse import urlencode

from core_ai.voice.session import VoiceConfig
from core_ai.voice.types import AudioFormat

GEMINI_LIVE_URL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"


def live_url(base_url: str, api_key: str) -> str:
    return f"{base_url}?{urlencode({'key': api_key})}"


def audio_mime_type(audio: AudioFormat) -> str:
    if audio.encoding != "pcm16":
        raise ValueError(f"Gemini Live takes PCM16 audio, not {audio.encoding}")
    return f"audio/pcm;rate={audio.sample_rate}"


def _function_declaration(tool: dict[str, Any]) -> dict[str, Any]:
    declaration = {"name": tool["name"], "description": tool.get("description", "")}
    if "parameters" in tool:
        declaration["parametersJsonSchema"] = tool["parameters"]
    return declaration


def setup_message(model_id: str, config: VoiceConfig, resume_handle: Optional[str]) -> dict[str, Any]:
    """The first client message. ``sessionResumption`` is always on: ``update`` reconnects
    with the latest handle, since Live config cannot change on an open connection."""
    generation: dict[str, Any] = {"responseModalities": ["AUDIO"]}
    if config.voice:
        generation["speechConfig"] = {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": config.voice}}}
    if config.reasoning_effort is not None:
        generation["thinkingConfig"] = {"thinkingLevel": config.reasoning_effort}
    resumption: dict[str, Any] = {"handle": resume_handle} if resume_handle else {}
    setup: dict[str, Any] = {
        "model": f"models/{model_id}",
        "generationConfig": generation,
        "systemInstruction": {"parts": [{"text": config.instructions}]},
        "realtimeInputConfig": {"automaticActivityDetection": {"disabled": config.turn_detection == "manual"}},
        "inputAudioTranscription": {},
        "outputAudioTranscription": {},
        "sessionResumption": resumption,
    }
    if config.tools:
        setup["tools"] = [{"functionDeclarations": [_function_declaration(tool) for tool in config.tools]}]
    return {"setup": setup}
