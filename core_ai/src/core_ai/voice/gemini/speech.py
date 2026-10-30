"""Gemini text-to-speech through the Interactions API (``POST /v1beta/interactions``), as
https://ai.google.dev/gemini-api/docs/speech-generation documents it: ``response_format``
``audio/l16`` is raw PCM16 at the requested ``sample_rate``; the audio is the last ``audio``
content of the ``model_output`` steps."""

import base64
from typing import Any

import httpx

GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


def speech_request(model: str, text: str, voice: str, sample_rate: int) -> dict[str, Any]:
    return {
        "model": model,
        "input": [{"type": "user_input", "content": [{"type": "text", "text": text}]}],
        "response_format": {"type": "audio", "mime_type": "audio/l16", "sample_rate": sample_rate},
        "generation_config": {"speech_config": [{"voice": voice}]},
    }


def output_audio(interaction: dict[str, Any]) -> bytes:
    audio = [
        content["data"]
        for step in interaction["steps"]
        if step["type"] == "model_output"
        for content in step["content"]
        if content["type"] == "audio"
    ]
    if not audio:
        raise ValueError("the interaction produced no audio")
    return base64.b64decode(audio[-1])


async def synthesize(
    api_key: str,
    model: str,
    text: str,
    voice: str,
    sample_rate: int = 24000,
    base_url: str = GEMINI_API_BASE_URL,
) -> bytes:
    """Speak ``text`` with Gemini TTS ``model`` in prebuilt ``voice``; raw PCM16 audio."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{base_url}/interactions",
            headers={"x-goog-api-key": api_key},
            json=speech_request(model, text, voice, sample_rate),
        )
    response.raise_for_status()
    return output_audio(response.json())
