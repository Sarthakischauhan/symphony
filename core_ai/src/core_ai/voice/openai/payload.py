"""The OpenAI ``session`` of a ``session.update`` (``RealtimeSessionCreateRequestGA`` in
https://github.com/openai/openai-openapi)."""

from typing import Any

from core_ai.voice.session import VoiceConfig
from core_ai.voice.types import AudioFormat

_AUDIO_TYPES: dict[str, str] = {
    "pcm16": "audio/pcm",
    "pcmu": "audio/pcmu",
    "pcma": "audio/pcma",
}
# Transcribes caller audio so the session reports what the user said; one of the spec's
# ``audio.input.transcription.model`` values.
INPUT_TRANSCRIPTION_MODEL = "gpt-4o-mini-transcribe"


def audio_format(audio: AudioFormat) -> dict[str, Any]:
    """The spec gives ``rate`` for ``audio/pcm`` only; G.711 has none."""
    wire: dict[str, Any] = {"type": _AUDIO_TYPES[audio.encoding]}
    if audio.encoding == "pcm16":
        wire["rate"] = audio.sample_rate
    return wire


def session_payload(config: VoiceConfig) -> dict[str, Any]:
    """The ``session`` object of a ``session.update`` for this config."""
    output: dict[str, Any] = {"format": audio_format(config.audio)}
    if config.voice:
        output["voice"] = config.voice
    session: dict[str, Any] = {
        "type": "realtime",
        "instructions": config.instructions,
        "audio": {
            "input": {
                "format": audio_format(config.audio),
                "transcription": {"model": INPUT_TRANSCRIPTION_MODEL},
                "turn_detection": {"type": "server_vad"} if config.turn_detection == "server_vad" else None,
            },
            "output": output,
        },
        "tools": [{"type": "function", **tool} for tool in config.tools],
    }
    if config.reasoning_effort is not None:
        session["reasoning"] = {"effort": config.reasoning_effort}
    return session
