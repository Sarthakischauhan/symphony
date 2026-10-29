"""Every generated catalog entry opens through ``open_voice_session`` on its provider's
realtime client, against a local fake server (no network)."""

import asyncio
import json
from typing import Any
from urllib.parse import urlencode

import pytest
from websockets.asyncio.server import ServerConnection, serve

from core_ai.voice import (
    VOICE_MODELS,
    GeminiVoiceSession,
    GrokVoiceSession,
    OpenAIVoiceSession,
    SarvamVoiceSession,
    VercelVoiceSession,
    VoiceConfig,
    VoiceModelSpec,
    open_voice_session,
)
from core_ai.voice import vercel

SESSION_CLASSES = {
    "grok": GrokVoiceSession,
    "openai": OpenAIVoiceSession,
    "gemini": GeminiVoiceSession,
    "vercel": VercelVoiceSession,
    "sarvam": SarvamVoiceSession,
}
# The session configuration frame each WebSocket client sends first (Live sends ``setup``).
# Sarvam configures in the URL query, so its first frame is the audio the test sends.
FIRST_FRAME_TYPES = {"grok": "session.update", "openai": "session.update", "vercel": "session-update"}


def _base_url(provider: str, port: int) -> str:
    if provider == "gemini":
        return f"ws://127.0.0.1:{port}/ws/live"
    if provider == "vercel":
        return f"http://127.0.0.1:{port}/v4/ai"
    if provider == "sarvam":
        return f"http://127.0.0.1:{port}"
    return f"http://127.0.0.1:{port}/v1"


def _expected_path(model: VoiceModelSpec) -> str:
    if model.provider == "gemini":
        return "/ws/live?key=key"
    if model.provider == "vercel":
        return f"/v4/ai/realtime-model?{urlencode({'ai-model-id': model.id})}"
    if model.provider == "sarvam":
        audio = model.audio_input[0]
        query = {"model": model.id, "language_code": "auto", "encoding": "linear16", "sample_rate": audio.sample_rate}
        return f"/speech-to-text-realtime/ws?{urlencode(query | {'endpointing': 'vad'})}"
    return f"/v1/realtime?model={model.id}"


def _opened_model(model: VoiceModelSpec, first: dict[str, Any]) -> str:
    """The model id the client's first frame configures (Live names it in ``setup``)."""
    if model.provider == "gemini":
        return first["setup"]["model"].removeprefix("models/")
    return model.id


def test_every_provider_has_catalog_entries() -> None:
    assert {model.provider for model in VOICE_MODELS} == set(SESSION_CLASSES)


@pytest.mark.parametrize("model", VOICE_MODELS, ids=lambda model: model.full_id)
def test_catalog_entry_opens_on_its_provider_client(model: VoiceModelSpec, monkeypatch: pytest.MonkeyPatch) -> None:
    minted: list[tuple[str, str]] = []

    async def mint(api_key: str, model_id: str, base_url: str) -> str:
        minted.append((api_key, model_id))
        return "vcst_token"

    monkeypatch.setattr(vercel.realtime, "mint_client_secret", mint)
    paths: list[str] = []
    frames: list[dict[str, Any]] = []
    first_frame = asyncio.Event()

    async def handler(connection: ServerConnection) -> None:
        assert connection.request is not None
        paths.append(connection.request.path)
        async for message in connection:
            frames.append(json.loads(message))
            first_frame.set()

    async def run() -> Any:
        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            if model.provider == "sarvam":
                # Realtime STT: no voice, and the model's own input format.
                config = VoiceConfig(voice="", audio=model.audio_input[0])
            else:
                config = VoiceConfig(voice=model.voices[0].id)
            session = await open_voice_session(model, config, api_key="key", base_url=_base_url(model.provider, port))
            if model.provider == "sarvam":
                await session.send_audio(b"\x00\x00")
            try:
                await asyncio.wait_for(first_frame.wait(), 5)
                return session
            finally:
                await session.aclose()

    session = asyncio.run(run())
    assert isinstance(session, SESSION_CLASSES[model.provider])
    assert session.model_id == model.id
    assert paths == [_expected_path(model)]
    first = frames[0]
    if model.provider == "gemini":
        assert "setup" in first
    elif model.provider == "sarvam":
        assert first["event"] == "audio_input"
    else:
        assert first["type"] == FIRST_FRAME_TYPES[model.provider]
    assert _opened_model(model, first) == model.id
    assert minted == ([("key", model.id)] if model.provider == "vercel" else [])
