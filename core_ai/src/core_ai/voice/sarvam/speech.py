"""Sarvam text-to-speech (``POST /text-to-speech``) and speech-to-text
(``POST /speech-to-text``), per https://docs.sarvam.ai/openapi/apis.json."""

import base64
from typing import Optional

import httpx

from core_ai.voice.sarvam.realtime import SARVAM_BASE_URL


async def synthesize(
    api_key: str,
    model: str,
    text: str,
    speaker: str,
    language_code: str,
    base_url: str = SARVAM_BASE_URL,
) -> bytes:
    """Speak ``text`` (in ``language_code``) with TTS ``model`` as ``speaker``; the decoded
    audio in the endpoint's default ``output_audio_codec`` (WAV)."""
    body = {"text": text, "model": model, "speaker": speaker, "language_code": language_code}
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(f"{base_url}/text-to-speech", headers={"api-subscription-key": api_key}, json=body)
    response.raise_for_status()
    audios: list[str] = response.json()["audios"]
    return b"".join(base64.b64decode(audio) for audio in audios)


async def transcribe(
    api_key: str,
    model: str,
    audio: bytes,
    filename: str,
    media_type: str,
    language_code: Optional[str] = None,
    base_url: str = SARVAM_BASE_URL,
) -> str:
    """The text of an audio file via STT ``model``; ``language_code`` None lets it detect."""
    data = {"model": model}
    if language_code:
        data["language_code"] = language_code
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{base_url}/speech-to-text",
            headers={"api-subscription-key": api_key},
            data=data,
            files={"file": (filename, audio, media_type)},
        )
    response.raise_for_status()
    text: str = response.json()["transcript"]
    return text
