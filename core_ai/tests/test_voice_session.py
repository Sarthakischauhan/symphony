import asyncio
import json
import logging
from typing import Any, Union

import pytest
from websockets.asyncio.server import ServerConnection, serve

from core_ai import list_models
from core_ai.models.generated import ALL_MODELS
from core_ai.models.registry import model_catalog
from core_ai.voice import (
    VOICE_MODELS,
    AudioDelta,
    GrokRealtime,
    ResponseDone,
    ResponseEvent,
    TextDelta,
    ToolCall,
    UserTranscript,
    VoiceConfig,
    VoiceEvent,
    VoiceRegistry,
    VoiceSession,
    voice_catalog,
)


def test_default_model_lists_have_no_realtime_models() -> None:
    assert all(m.api != "realtime" for m in ALL_MODELS)
    assert all(m.api != "realtime" for m in list_models())
    assert all(m.api != "realtime" for m in model_catalog.list())


def test_voice_catalog_lists_grok_realtime_models_with_voices() -> None:
    assert voice_catalog.list() == tuple(sorted(VOICE_MODELS, key=lambda m: (m.provider, m.id)))
    assert {m.id for m in voice_catalog.list("grok")} == {"grok-voice-3.0", "grok-voice-latest"}
    model = voice_catalog.get("grok", "grok-voice-latest")
    assert model is not None and model.api == "realtime"
    assert len(model.voices) == 28
    assert model.default_voice == "eve"
    assert model.reasoning_efforts == ("none", "high")
    assert "audio" in model.input_modalities and "audio" in model.output_modalities


def test_voice_registry_lists_models_of_registered_providers() -> None:
    registry = VoiceRegistry()
    assert registry.models() == ()
    registry.register("grok", GrokRealtime("key"))
    assert {m.id for m in registry.models()} == {"grok-voice-3.0", "grok-voice-latest"}
    registry.unregister("grok")
    assert registry.namespaces() == ()
    with pytest.raises(KeyError):
        asyncio.run(registry.open("grok:grok-voice-latest", VoiceConfig(voice="eve")))


Frame = Union[str, bytes]


def _event(payload: dict[str, Any]) -> str:
    return json.dumps(payload)


def _created(response_id: str) -> str:
    return _event({"type": "response.created", "response": {"id": response_id}})


def _text(response_id: str, text: str) -> str:
    return _event({"type": "response.output_audio_transcript.delta", "response_id": response_id, "delta": text})


def _done(response_id: str) -> str:
    return _event({"type": "response.done", "response": {"id": response_id, "status": "completed"}})


async def _with_fake_xai(
    on_message: dict[str, list[Frame]],
    opening: list[Frame],
    received: list[dict[str, Any]],
    body: Any,
    config: VoiceConfig = VoiceConfig(voice="eve"),
    observed: list[str] | None = None,
) -> Any:
    """Serve a fake xAI realtime socket: ``opening`` on connect, then the frames keyed by each
    client event type as it arrives."""

    async def handler(connection: ServerConnection) -> None:
        for frame in opening:
            await connection.send(frame)
        async for message in connection:
            if isinstance(message, str):
                received.append(json.loads(message))
                for frame in on_message.get(received[-1]["type"], []):
                    await connection.send(frame)

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        registry = VoiceRegistry()
        registry.register("grok", GrokRealtime("key", base_url=f"http://127.0.0.1:{port}/v1"))
        frames: list[str] = []
        session = await registry.open("grok:grok-voice-latest", config, observer=lambda d, f: frames.append(d))
        try:
            return await body(session)
        finally:
            await session.aclose()
            if observed is not None:
                observed.extend(frames)


def test_grok_voice_session_over_the_wire() -> None:
    received: list[dict[str, Any]] = []
    opening: list[Frame] = [
        _event({"type": "conversation.item.input_audio_transcription.completed", "transcript": " hi there "}),
        _event({"type": "input_audio_buffer.speech_stopped"}),
        _created("r1"),
        b"\x01\x02",
        _text("r1", "Hey"),
        _event({"type": "response.function_call_arguments.done", "response_id": "r1", "call_id": "c1",
                "name": "get_weather", "arguments": "{}"}),
        _event({"type": "response.output_item.done", "response_id": "r1",
                "item": {"type": "function_call", "call_id": "c1", "name": "get_weather", "arguments": "{}"}}),
        _event({"type": "response.done", "response": {"id": "r1", "status": "completed",
                                                       "usage": {"input_tokens": 5, "output_tokens": 2}}}),
    ]
    # Audio of the cancelled response still in flight, then the next response's audio.
    on_message: dict[str, list[Frame]] = {"response.create": [_created("r2")],
                                          "response.cancel": [b"\x09", _done("r2"), b"\x03"]}

    async def body(session: VoiceSession) -> tuple[list[VoiceEvent], list[ResponseEvent]]:
        events = session.events()
        seen = [await anext(events), await anext(events), await anext(events)]
        first = [e async for e in session.response()]
        await session.respond()
        await asyncio.sleep(0.05)
        await session.cancel()
        await session.cancel()
        seen.append(await anext(events))
        await session.add_tool_result("c1", "sunny")
        await asyncio.sleep(0.05)
        return seen, first

    config = VoiceConfig(voice="ara", tools=({"name": "get_weather", "parameters": {}},))
    observed: list[str] = []
    seen, first = asyncio.run(_with_fake_xai(on_message, opening, received, body, config, observed))

    assert "received" in observed and "sent" in observed

    assert [type(e).__name__ for e in seen[:2]] == ["UserTranscript", "SpeechStopped"]
    assert seen[0] == UserTranscript("hi there")
    assert seen[2:] == [AudioDelta(b"\x01\x02"), AudioDelta(b"\x03")]
    assert first == [TextDelta("Hey"), ToolCall("c1", "get_weather", "{}"), ResponseDone(5, 2)]
    update = received[0]
    assert update["type"] == "session.update"
    assert update["session"]["voice"] == "ara"
    assert update["session"]["tools"] == [{"type": "function", "name": "get_weather", "parameters": {}}]
    assert update["session"]["audio"]["input"]["format"] == {"type": "audio/pcm", "rate": 24000}
    assert [e["type"] for e in received[1:]] == ["response.create", "response.cancel", "conversation.item.create"]


def test_unrequested_response_is_dropped(caplog: pytest.LogCaptureFixture) -> None:
    received: list[dict[str, Any]] = []
    # The server starts r0 on its own (no response.create, no committed speech).
    opening: list[Frame] = [_created("r0"), b"\x07", _text("r0", "unprompted"), _done("r0")]
    on_message: dict[str, list[Frame]] = {"response.create": [_created("r1"), _text("r1", "asked"), _done("r1")]}

    async def body(session: VoiceSession) -> list[ResponseEvent]:
        await asyncio.sleep(0.05)
        await session.respond()
        return [e async for e in session.response()]

    with caplog.at_level(logging.DEBUG, logger="core_ai.voice.grok.realtime"):
        events = asyncio.run(_with_fake_xai(on_message, opening, received, body))

    assert events == [TextDelta("asked"), ResponseDone()]
    assert "dropping unrequested voice response r0" in caplog.text


def test_each_requested_response_reaches_its_own_request() -> None:
    received: list[dict[str, Any]] = []
    # Speech committed under server VAD requests r1; the explicit response.create requests r2.
    # A spontaneous r9 arrives between them and belongs to neither.
    opening: list[Frame] = [
        _event({"type": "input_audio_buffer.speech_stopped"}),
        _created("r1"), _text("r1", "for speech"), _done("r1"),
        _created("r9"), _text("r9", "stray"), _done("r9"),
    ]
    on_message: dict[str, list[Frame]] = {"response.create": [_created("r2"), _text("r2", "for typed"), _done("r2")]}

    async def body(session: VoiceSession) -> tuple[list[ResponseEvent], list[ResponseEvent]]:
        spoken = [e async for e in session.response()]
        await asyncio.sleep(0.05)
        await session.respond()
        typed = [e async for e in session.response()]
        return spoken, typed

    spoken, typed = asyncio.run(_with_fake_xai(on_message, opening, received, body))

    assert spoken == [TextDelta("for speech"), ResponseDone()]
    assert typed == [TextDelta("for typed"), ResponseDone()]


def test_closed_connection_ends_a_waiting_response() -> None:
    async def body(session: VoiceSession) -> list[ResponseEvent]:
        await session.respond()
        waiting = asyncio.ensure_future(_collect(session))
        await asyncio.sleep(0.05)
        await session.aclose()
        return await waiting

    async def _collect(session: VoiceSession) -> list[ResponseEvent]:
        return [e async for e in session.response()]

    events = asyncio.run(_with_fake_xai({}, [], [], body))
    assert events == [ResponseDone(error="the voice connection closed")]
