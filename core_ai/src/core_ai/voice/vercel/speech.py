"""AI Gateway text-to-speech and speech-to-text over its REST model routes.

``POST {base}/speech-model`` and ``POST {base}/transcription-model`` with the model in the
``ai-model-id`` header, as ``GatewaySpeechModel`` / ``GatewayTranscriptionModel`` send them
(https://github.com/vercel/ai, packages/gateway). Models are the gateway's ``speech`` and
``transcription`` entries in the public ``GET https://ai-gateway.vercel.sh/v1/models``.
"""

import base64
from typing import Any, Optional

import httpx

from core_ai.voice.vercel.payload import AI_GATEWAY_BASE_URL
from core_ai.voice.vercel.realtime import gateway_headers


async def _post(api_key: str, url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, headers={**gateway_headers(api_key), **headers}, json=body)
    response.raise_for_status()
    payload: dict[str, Any] = response.json()
    return payload


async def synthesize(
    api_key: str,
    model: str,
    text: str,
    voice: Optional[str] = None,
    output_format: Optional[str] = None,
    base_url: str = AI_GATEWAY_BASE_URL,
) -> bytes:
    """Speak ``text`` with gateway speech ``model``; the audio in ``output_format`` (or the
    model's default)."""
    body: dict[str, Any] = {"text": text}
    if voice:
        body["voice"] = voice
    if output_format:
        body["outputFormat"] = output_format
    headers = {"ai-speech-model-specification-version": "4", "ai-model-id": model}
    payload = await _post(api_key, f"{base_url}/speech-model", headers, body)
    return base64.b64decode(payload["audio"])


async def transcribe(
    api_key: str,
    model: str,
    audio: bytes,
    media_type: str,
    base_url: str = AI_GATEWAY_BASE_URL,
) -> str:
    """The text of ``audio`` (of ``media_type``) via gateway transcription ``model``."""
    body = {"audio": base64.b64encode(audio).decode(), "mediaType": media_type}
    headers = {"ai-transcription-model-specification-version": "4", "ai-model-id": model}
    payload = await _post(api_key, f"{base_url}/transcription-model", headers, body)
    text: str = payload["text"]
    return text
