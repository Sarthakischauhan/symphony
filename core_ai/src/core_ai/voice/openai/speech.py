"""OpenAI text-to-speech (``POST /v1/audio/speech``) and speech-to-text
(``POST /v1/audio/transcriptions``), per ``CreateSpeechRequest`` and
``CreateTranscriptionRequest`` in https://github.com/openai/openai-openapi."""

from typing import Optional

import httpx

from core_ai.voice.openai.realtime import OPENAI_BASE_URL

# ``response_format: pcm`` is raw 24 kHz 16-bit little-endian PCM.
SPEECH_FORMAT = "pcm"


async def synthesize(
    api_key: str,
    model: str,
    text: str,
    voice: str,
    instructions: Optional[str] = None,
    base_url: str = OPENAI_BASE_URL,
) -> bytes:
    """Speak ``text`` with TTS ``model`` in ``voice``; raw PCM16 audio."""
    body: dict[str, str] = {"model": model, "input": text, "voice": voice, "response_format": SPEECH_FORMAT}
    if instructions:
        body["instructions"] = instructions
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{base_url}/audio/speech", headers={"Authorization": f"Bearer {api_key}"}, json=body
        )
    response.raise_for_status()
    return response.content


async def transcribe(
    api_key: str,
    model: str,
    audio: bytes,
    filename: str,
    media_type: str,
    base_url: str = OPENAI_BASE_URL,
) -> str:
    """The text of an audio file (``filename``'s extension names its format) via STT ``model``."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{base_url}/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            data={"model": model},
            files={"file": (filename, audio, media_type)},
        )
    response.raise_for_status()
    text: str = response.json()["text"]
    return text
