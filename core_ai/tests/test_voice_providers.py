"""OpenAI, Gemini Live and AI Gateway realtime clients against fake servers, plus their
payload and event mapping and their TTS / STT requests."""

import asyncio
import base64
import json
from dataclasses import replace
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from websockets.asyncio.server import ServerConnection, serve

from core_ai.voice import (
    AudioDelta,
    AudioFormat,
    ResponseDone,
    SPEECH_MODELS,
    SarvamResponsesUnsupported,
    SpeechStarted,
    SpeechStopped,
    TextDelta,
    ToolCall,
    UserTranscript,
    VOICE_MODELS,
    VoiceConfig,
    VoiceError,
    VoiceEvent,
    VoiceModelSpec,
    VoiceSession,
    open_voice_session,
    voice_model,
)
from core_ai.voice import gemini, openai, sarvam, vercel
from core_ai.voice.gemini.payload import audio_mime_type, setup_message
from core_ai.voice.gemini.speech import output_audio, speech_request
from core_ai.voice.openai.payload import INPUT_TRANSCRIPTION_MODEL, session_payload
from core_ai.voice.vercel.payload import client_secret_url, realtime_url, session_config

TOOL = {"name": "get_weather", "description": "Weather", "parameters": {"type": "object", "properties": {}}}
Handler = Callable[[ServerConnection], Awaitable[None]]
Body = Callable[[VoiceSession], Awaitable[Any]]


def _b64(audio: bytes) -> str:
    return base64.b64encode(audio).decode()


def _model(full_id: str) -> VoiceModelSpec:
    """A catalog model; Gemini's list needs an API key, so its spec is a stand-in."""
    if full_id.startswith("gemini:"):
        return replace(VOICE_MODELS[0], provider="gemini", id=full_id.removeprefix("gemini:"))
    return next(model for model in VOICE_MODELS if f"{model.provider}:{model.id}" == full_id)


async def _serve(handler: Handler, full_id: str, body: Body, base_url: Callable[[int], str]) -> Any:
    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        model = _model(full_id)
        session = await open_voice_session(model, CONFIG, api_key="key", base_url=base_url(port))
        try:
            return await body(session)
        finally:
            await session.aclose()


async def _collect(session: VoiceSession, count: int) -> list[VoiceEvent]:
    events: list[VoiceEvent] = []
    async for event in session.events():
        events.append(event)
        if len(events) == count:
            return events
    return events


async def _response(session: VoiceSession) -> list[Any]:
    return [event async for event in session.response()]


ASYNC_CLIENT = httpx.AsyncClient
CONFIG = VoiceConfig(voice="marin", instructions="Be brief.", tools=(TOOL,))


# OpenAI


def test_openai_session_payload_follows_the_ga_session_shape() -> None:
    payload = session_payload(replace_audio(CONFIG, AudioFormat("pcmu", 8000), effort="low"))
    assert payload["type"] == "realtime"
    assert payload["audio"]["input"] == {
        "format": {"type": "audio/pcmu"},
        "transcription": {"model": INPUT_TRANSCRIPTION_MODEL},
        "turn_detection": {"type": "server_vad"},
    }
    assert payload["audio"]["output"] == {"format": {"type": "audio/pcmu"}, "voice": "marin"}
    assert payload["tools"] == [{"type": "function", **TOOL}]
    assert payload["reasoning"] == {"effort": "low"}
    pcm = session_payload(VoiceConfig(voice="", turn_detection="manual"))
    assert pcm["audio"]["input"]["format"] == {"type": "audio/pcm", "rate": 24000}
    assert pcm["audio"]["input"]["turn_detection"] is None
    assert "voice" not in pcm["audio"]["output"]


def replace_audio(config: VoiceConfig, audio: AudioFormat, effort: str) -> VoiceConfig:
    return VoiceConfig(config.voice, config.instructions, config.tools, effort, audio, config.turn_detection)


def test_openai_realtime_over_the_wire() -> None:
    received: list[dict[str, Any]] = []
    paths: list[str] = []
    auth: list[str] = []

    async def handler(connection: ServerConnection) -> None:
        assert connection.request is not None
        paths.append(connection.request.path)
        auth.append(connection.request.headers["Authorization"])
        async for message in connection:
            event = json.loads(message)
            received.append(event)
            if event["type"] == "response.create":
                metadata = event["response"]["metadata"]
                for frame in (
                    {"type": "response.created", "response": {"id": "r1", "metadata": metadata}},
                    {"type": "response.output_audio.delta", "response_id": "r1", "delta": _b64(b"\x05\x06")},
                    {"type": "response.output_audio_transcript.delta", "response_id": "r1", "delta": "Hi"},
                    {
                        "type": "response.done",
                        "response": {
                            "id": "r1",
                            "status": "completed",
                            "usage": {"input_tokens": 3, "output_tokens": 4},
                        },
                    },
                ):
                    await connection.send(json.dumps(frame))

    async def body(session: VoiceSession) -> tuple[list[VoiceEvent], list[Any]]:
        await session.send_audio(b"\x01\x02")
        await session.add_message("user", "hello")
        await session.respond()
        return await _collect(session, 1), await _response(session)

    events, response = asyncio.run(
        _serve(handler, "openai:gpt-realtime", body, lambda port: f"http://127.0.0.1:{port}/v1")
    )
    assert paths == ["/v1/realtime?model=gpt-realtime"]
    assert auth == ["Bearer key"]
    assert [event["type"] for event in received] == [
        "session.update",
        "input_audio_buffer.append",
        "conversation.item.create",
        "response.create",
    ]
    assert received[0]["session"]["audio"]["output"]["voice"] == "marin"
    assert received[1]["audio"] == _b64(b"\x01\x02")
    assert events == [AudioDelta(b"\x05\x06")]
    assert response == [TextDelta("Hi"), ResponseDone(input_tokens=3, output_tokens=4)]


def test_openai_catalog_models_come_from_the_published_spec() -> None:
    model = voice_model("openai:gpt-realtime")
    assert model is not None
    assert model.default_voice == "alloy"
    assert {"marin", "cedar"} <= {voice.id for voice in model.voices}
    assert model.audio_input == (AudioFormat("pcm16", 24000), AudioFormat("pcmu", 8000), AudioFormat("pcma", 8000))


class _Recorded:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.requests: list[httpx.Request] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        transport = httpx.MockTransport(self.handle)

        def client(**kwargs: Any) -> httpx.AsyncClient:
            return ASYNC_CLIENT(transport=transport, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", client)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.response


def test_openai_speech_and_transcription_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    speech = _Recorded(httpx.Response(200, content=b"\x00\x01"))
    speech.install(monkeypatch)
    assert asyncio.run(openai.synthesize("key", "gpt-4o-mini-tts", "Hi", "marin")) == b"\x00\x01"
    request = speech.requests[0]
    assert str(request.url) == "https://api.openai.com/v1/audio/speech"
    assert json.loads(request.content) == {
        "model": "gpt-4o-mini-tts",
        "input": "Hi",
        "voice": "marin",
        "response_format": "pcm",
    }
    stt = _Recorded(httpx.Response(200, json={"text": "hello"}))
    stt.install(monkeypatch)
    assert asyncio.run(openai.transcribe("key", "whisper-1", b"RIFF", "a.wav", "audio/wav")) == "hello"
    request = stt.requests[0]
    assert str(request.url) == "https://api.openai.com/v1/audio/transcriptions"
    assert request.headers["Authorization"] == "Bearer key"
    assert b'name="model"' in request.content and b"whisper-1" in request.content


# AI Gateway


def test_gateway_urls_and_session_config() -> None:
    base = "https://ai-gateway.vercel.sh/v4/ai"
    assert realtime_url(base, "openai/gpt-realtime-2") == (
        "wss://ai-gateway.vercel.sh/v4/ai/realtime-model?ai-model-id=openai%2Fgpt-realtime-2"
    )
    assert client_secret_url(base) == "https://ai-gateway.vercel.sh/v1/realtime/client-secrets"
    config = session_config(CONFIG, "openai/gpt-realtime-2")
    assert "providerOptions" not in config
    assert config["voice"] == "marin"
    assert config["inputAudioFormat"] == {"type": "audio/pcm", "rate": 24000}
    assert config["turnDetection"] == {"type": "server-vad"}
    assert config["tools"] == [{"type": "function", **TOOL}]
    assert (
        session_config(VoiceConfig(voice="", turn_detection="manual"), "openai/gpt-realtime-2")["turnDetection"] is None
    )


def test_gateway_sends_google_effort_as_thinking_level() -> None:
    thinking = VoiceConfig(voice="Kore", reasoning_effort="low")
    assert session_config(thinking, "google/gemini-3.8-live")["providerOptions"] == {
        "google": {"thinkingConfig": {"thinkingLevel": "LOW"}}
    }
    with pytest.raises(ValueError, match="no realtime reasoning effort option"):
        session_config(thinking, "openai/gpt-realtime-2")


def test_gateway_realtime_over_the_wire(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[dict[str, Any]] = []
    connected: list[tuple[str, str]] = []
    minted: list[tuple[str, str, str]] = []

    async def mint(api_key: str, model_id: str, base_url: str) -> str:
        minted.append((api_key, model_id, base_url))
        return "vcst_token"

    monkeypatch.setattr(vercel.realtime, "mint_client_secret", mint)

    async def handler(connection: ServerConnection) -> None:
        assert connection.request is not None
        connected.append((connection.request.path, connection.request.headers["Sec-WebSocket-Protocol"]))
        async for message in connection:
            event = json.loads(message)
            received.append(event)
            if event["type"] == "input-audio-append":
                for frame in (
                    {"type": "speech-stopped"},
                    {"type": "input-transcription-completed", "itemId": "i1", "transcript": " weather? "},
                    {"type": "response-created", "responseId": "r1"},
                    {"type": "audio-delta", "responseId": "r1", "itemId": "o1", "delta": _b64(b"\x07")},
                    {
                        "type": "function-call-arguments-done",
                        "responseId": "r1",
                        "itemId": "o1",
                        "callId": "c1",
                        "name": "get_weather",
                        "arguments": "{}",
                    },
                    {"type": "response-done", "responseId": "r1", "status": "completed"},
                ):
                    await connection.send(json.dumps(frame))
            if event["type"] == "response-create":
                for frame in (
                    {"type": "response-created", "responseId": "r2"},
                    {"type": "audio-transcript-delta", "responseId": "r2", "itemId": "o2", "delta": "Sunny"},
                    {"type": "response-done", "responseId": "r2", "status": "failed"},
                ):
                    await connection.send(json.dumps(frame))

    async def body(session: VoiceSession) -> tuple[list[VoiceEvent], list[Any], list[Any]]:
        await session.send_audio(b"\x01")
        events = await _collect(session, 3)
        first = await _response(session)
        await session.add_tool_result("c1", '{"sky": "clear"}')
        with pytest.raises(vercel.GatewayHistoryUnsupported):
            await session.add_message("assistant", "earlier")
        await session.respond()
        return events, first, await _response(session)

    events, first, second = asyncio.run(
        _serve(handler, "vercel:openai/gpt-realtime-2", body, lambda port: f"http://127.0.0.1:{port}/v4/ai")
    )
    assert minted[0][:2] == ("key", "openai/gpt-realtime-2")
    assert connected == [
        (
            "/v4/ai/realtime-model?ai-model-id=openai%2Fgpt-realtime-2",
            "ai-gateway-realtime.v1, ai-gateway-auth.vcst_token",
        )
    ]
    assert [event["type"] for event in received] == [
        "session-update",
        "input-audio-append",
        "conversation-item-create",
        "response-create",
    ]
    assert received[2]["item"] == {
        "type": "function-call-output",
        "callId": "c1",
        "output": '{"sky": "clear"}',
        "name": "get_weather",
    }
    assert events == [SpeechStopped(), UserTranscript("weather?"), AudioDelta(b"\x07")]
    assert first == [ToolCall("c1", "get_weather", "{}"), ResponseDone()]
    assert second == [TextDelta("Sunny"), ResponseDone(error="failed")]


def test_gateway_speech_and_transcription_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    speech = _Recorded(httpx.Response(200, json={"audio": _b64(b"\x09")}))
    speech.install(monkeypatch)
    assert asyncio.run(vercel.synthesize("key", "openai/tts-1", "Hi", voice="alloy")) == b"\x09"
    request = speech.requests[0]
    assert str(request.url) == "https://ai-gateway.vercel.sh/v4/ai/speech-model"
    assert request.headers["ai-model-id"] == "openai/tts-1"
    assert request.headers["ai-speech-model-specification-version"] == "4"
    assert json.loads(request.content) == {"text": "Hi", "voice": "alloy"}
    stt = _Recorded(httpx.Response(200, json={"text": "hello"}))
    stt.install(monkeypatch)
    assert asyncio.run(vercel.transcribe("key", "openai/whisper-1", b"\x01", "audio/wav")) == "hello"
    request = stt.requests[0]
    assert str(request.url) == "https://ai-gateway.vercel.sh/v4/ai/transcription-model"
    assert request.headers["ai-transcription-model-specification-version"] == "4"
    assert json.loads(request.content) == {"audio": _b64(b"\x01"), "mediaType": "audio/wav"}


# Gemini Live


def test_gemini_setup_message() -> None:
    setup = setup_message("gemini-live", CONFIG, resume_handle=None)["setup"]
    assert setup["model"] == "models/gemini-live"
    assert setup["generationConfig"] == {
        "responseModalities": ["AUDIO"],
        "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "marin"}}},
    }
    assert setup["systemInstruction"] == {"parts": [{"text": "Be brief."}]}
    assert setup["tools"] == [
        {
            "functionDeclarations": [
                {"name": "get_weather", "description": "Weather", "parametersJsonSchema": TOOL["parameters"]}
            ]
        }
    ]
    assert setup["realtimeInputConfig"] == {"automaticActivityDetection": {"disabled": False}}
    assert setup["sessionResumption"] == {}
    resumed = setup_message("gemini-live", VoiceConfig(voice="", turn_detection="manual"), "h1")["setup"]
    assert resumed["sessionResumption"] == {"handle": "h1"}
    assert "speechConfig" not in resumed["generationConfig"] and "tools" not in resumed
    assert resumed["realtimeInputConfig"] == {"automaticActivityDetection": {"disabled": True}}
    assert audio_mime_type(AudioFormat("pcm16", 16000)) == "audio/pcm;rate=16000"
    with pytest.raises(ValueError):
        audio_mime_type(AudioFormat("pcmu", 8000))


def _content(**fields: Any) -> str:
    return json.dumps({"serverContent": fields})


def test_gemini_live_over_the_wire() -> None:
    received: list[dict[str, Any]] = []
    urls: list[str] = []

    async def handler(connection: ServerConnection) -> None:
        assert connection.request is not None
        urls.append(connection.request.path)
        async for message in connection:
            event = json.loads(message)
            received.append(event)
            if "setup" in event:
                await connection.send(json.dumps({"setupComplete": {}}))
                await connection.send(json.dumps({"sessionResumptionUpdate": {"newHandle": "h1", "resumable": True}}))
            elif event.get("clientContent", {}).get("turnComplete"):
                # Binary frames carry JSON too.
                await connection.send(_content(inputTranscription={"text": "weather"}).encode())
                await connection.send(
                    _content(modelTurn={"parts": [{"inlineData": {"data": _b64(b"\x03"), "mimeType": "audio/pcm"}}]})
                )
                await connection.send(
                    json.dumps(
                        {"toolCall": {"functionCalls": [{"id": "f1", "name": "get_weather", "args": {"city": "SF"}}]}}
                    )
                )
            elif "toolResponse" in event:
                await connection.send(_content(outputTranscription={"text": "Sunny"}))
                await connection.send(json.dumps({"usageMetadata": {"promptTokenCount": 5, "responseTokenCount": 6}}))
                await connection.send(_content(turnComplete=True))

    async def body(session: VoiceSession) -> tuple[list[VoiceEvent], list[Any], list[Any]]:
        await session.send_audio(b"\x01\x02")
        await session.add_message("assistant", "Earlier reply")
        await asyncio.sleep(0.05)  # the resumption handle arrives
        await session.update(VoiceConfig(voice="Kore", audio=AudioFormat("pcm16", 16000)))
        await session.respond()
        first = await _response(session)
        await session.add_tool_result("f1", '{"sky": "clear"}')
        await session.respond()
        second = await _response(session)
        return await _collect(session, 2), first, second

    events, first, second = asyncio.run(
        _serve(handler, "gemini:gemini-live", body, lambda port: f"ws://127.0.0.1:{port}/ws/live")
    )
    assert urls == ["/ws/live?key=key", "/ws/live?key=key"]
    setups = [event["setup"] for event in received if "setup" in event]
    assert setups[0]["sessionResumption"] == {} and setups[1]["sessionResumption"] == {"handle": "h1"}
    assert setups[1]["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Kore"
    assert received[1] == {"realtimeInput": {"audio": {"data": _b64(b"\x01\x02"), "mimeType": "audio/pcm;rate=24000"}}}
    assert received[2] == {
        "clientContent": {"turns": [{"role": "model", "parts": [{"text": "Earlier reply"}]}], "turnComplete": False}
    }
    assert received[4] == {"clientContent": {"turnComplete": True}}
    assert received[5] == {
        "toolResponse": {
            "functionResponses": [{"id": "f1", "name": "get_weather", "response": {"output": '{"sky": "clear"}'}}]
        }
    }
    assert len(received) == 6  # respond() after a toolResponse sends nothing: Live continues itself
    assert first == [ToolCall("f1", "get_weather", '{"city": "SF"}'), ResponseDone()]
    assert second == [TextDelta("Sunny"), ResponseDone(input_tokens=5, output_tokens=6)]
    assert events == [UserTranscript("weather"), AudioDelta(b"\x03")]


def test_gemini_update_needs_a_resumable_point() -> None:
    async def handler(connection: ServerConnection) -> None:
        async for _ in connection:
            pass

    async def body(session: VoiceSession) -> None:
        with pytest.raises(gemini.GeminiNotResumable):
            await session.update(VoiceConfig(voice="Puck"))

    asyncio.run(_serve(handler, "gemini:gemini-live", body, lambda port: f"ws://127.0.0.1:{port}/ws/live"))


def test_gemini_speech_request_and_audio() -> None:
    request = speech_request("gemini-tts", "Hi", "Kore", 24000)
    assert request["response_format"] == {"type": "audio", "mime_type": "audio/l16", "sample_rate": 24000}
    assert request["generation_config"] == {"speech_config": [{"voice": "Kore"}]}
    interaction = {
        "steps": [
            {"type": "user_input", "content": []},
            {"type": "model_output", "content": [{"type": "audio", "data": _b64(b"\x01")}]},
            {"type": "model_output", "content": [{"type": "audio", "data": _b64(b"\x02")}]},
        ]
    }
    assert output_audio(interaction) == b"\x02"


# Sarvam


def _sarvam_model(model_id: str) -> VoiceModelSpec:
    return next(m for m in VOICE_MODELS if m.provider == "sarvam" and m.id == model_id)


async def _serve_sarvam(handler: Handler, config: VoiceConfig, body: Body) -> Any:
    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        session = await open_voice_session(
            _sarvam_model("saaras:v3-realtime"), config, api_key="key", base_url=f"http://127.0.0.1:{port}"
        )
        try:
            return await body(session)
        finally:
            await session.aclose()


def test_sarvam_realtime_transcribes_over_the_wire() -> None:
    received: list[dict[str, Any]] = []
    requests: list[tuple[str, str]] = []

    async def handler(connection: ServerConnection) -> None:
        assert connection.request is not None
        requests.append((connection.request.path, connection.request.headers["api-subscription-key"]))
        async for message in connection:
            received.append(json.loads(message))
            for frame in (
                {"event": "session.begin", "request_id": "q"},
                {"event": "vad.speech_start", "utterance_idx": 0},
                {"event": "transcript.partial", "utterance_idx": 0, "text": "nam"},
                {"event": "vad.speech_end", "utterance_idx": 0},
                {"event": "transcript.final", "utterance_idx": 0, "text": " namaste "},
                {"event": "error", "code": "x", "is_fatal": False, "message": "slow down"},
            ):
                await connection.send(json.dumps(frame))

    async def body(session: VoiceSession) -> list[VoiceEvent]:
        await session.send_audio(b"\x01\x02")
        return await _collect(session, 4)

    config = VoiceConfig(voice="", audio=AudioFormat("pcm16", 16000), language="hi-IN")
    events = asyncio.run(_serve_sarvam(handler, config, body))
    path, key = requests[0]
    assert key == "key"
    assert path == (
        "/speech-to-text-realtime/ws?model=saaras%3Av3-realtime&language_code=hi-IN"
        "&encoding=linear16&sample_rate=16000&endpointing=vad"
    )
    assert received == [{"event": "audio_input", "audio": _b64(b"\x01\x02")}]
    assert events == [SpeechStarted(), SpeechStopped(), UserTranscript("namaste"), VoiceError("slow down")]


def test_sarvam_manual_turns_and_unsupported_calls() -> None:
    received: list[dict[str, Any]] = []

    async def handler(connection: ServerConnection) -> None:
        async for message in connection:
            received.append(json.loads(message))

    async def body(session: VoiceSession) -> None:
        await session.send_audio(b"\x01")
        await session.send_audio(b"\x02")
        await session.respond()
        await session.update(replace(config, language="ta-IN"))
        for call in (
            session.add_message("user", "hi"),
            session.add_tool_call("c", "f", "{}"),
            session.add_tool_result("c", "{}"),
            session.cancel(),
            session.update(replace(config, turn_detection="server_vad")),
        ):
            with pytest.raises(SarvamResponsesUnsupported):
                await call
        with pytest.raises(SarvamResponsesUnsupported):
            session.response()
        await asyncio.sleep(0.05)

    config = VoiceConfig(voice="", audio=AudioFormat("pcmu", 8000), turn_detection="manual")
    asyncio.run(_serve_sarvam(handler, config, body))
    assert [frame["event"] for frame in received] == [
        "speech_start",
        "audio_input",
        "audio_input",
        "speech_end",
        "config.update",
    ]
    assert received[-1]["language_code"] == "ta-IN"


def test_sarvam_speech_and_transcription_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    speech = _Recorded(httpx.Response(200, json={"request_id": "r", "audios": [_b64(b"RI"), _b64(b"FF")]}))
    speech.install(monkeypatch)
    assert asyncio.run(sarvam.synthesize("key", "bulbul:v3", "Hi", "shubh", "hi-IN")) == b"RIFF"
    request = speech.requests[0]
    assert str(request.url) == "https://api.sarvam.ai/text-to-speech"
    assert request.headers["api-subscription-key"] == "key"
    assert json.loads(request.content) == {
        "text": "Hi",
        "model": "bulbul:v3",
        "speaker": "shubh",
        "language_code": "hi-IN",
    }
    stt = _Recorded(httpx.Response(200, json={"transcript": "hello", "language_code": "en-IN"}))
    stt.install(monkeypatch)
    assert asyncio.run(sarvam.transcribe("key", "saaras:v3", b"RIFF", "a.wav", "audio/wav")) == "hello"
    request = stt.requests[0]
    assert str(request.url) == "https://api.sarvam.ai/speech-to-text"
    assert b'name="model"' in request.content and b"saaras:v3" in request.content
    assert b'name="language_code"' not in request.content


def test_sarvam_speech_catalog_lists_each_models_speakers() -> None:
    tts = {m.id: m for m in SPEECH_MODELS if m.kind == "tts"}
    for model in tts.values():
        assert model.provider == "sarvam" and model.voices and model.languages
        assert model.default_voice in {voice.id for voice in model.voices}
    assert all(m.provider == "sarvam" and not m.voices and m.languages for m in SPEECH_MODELS if m.kind == "stt")
