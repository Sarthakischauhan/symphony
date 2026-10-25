import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any, Literal, Union

import pytest
from websockets.asyncio.server import ServerConnection, serve

from core_ai import GrokProvider, Message, ModelRegistry, get_model, list_models
from core_ai.voice import (
    AudioDelta,
    ResponseDone,
    ResponseEvent,
    TextDelta,
    ToolCall,
    UserTranscript,
    VoiceConfig,
    VoiceEvent,
    VoiceHistory,
    VoiceModelCall,
    VoiceSession,
    VoiceSessionNotOpen,
    voice_model_call,
)


def test_catalog_lists_grok_realtime_models_with_voices() -> None:
    realtime = [m for m in list_models("grok") if m.api == "realtime"]

    assert {m.id for m in realtime} == {"grok-voice-3.0", "grok-voice-latest"}
    model = get_model("grok", "grok-voice-latest")
    assert model is not None
    assert len(model.voices) == 28
    assert model.default_voice == "eve"
    assert model.reasoning_efforts == ("none", "high")
    assert "audio" in model.input_modalities and "audio" in model.output_modalities


class FakeSession(VoiceSession):
    """Records what a model call sends and replays one scripted response."""

    def __init__(self, script: list[ResponseEvent], turn_detection: Literal["server_vad", "manual"] = "server_vad"):
        self.model_id = "grok-voice-latest"
        self.config = VoiceConfig(voice="eve", turn_detection=turn_detection)
        self.history = VoiceHistory()
        self.sent: list[tuple[str, ...]] = []
        self.script = script

    async def send_audio(self, audio: bytes) -> None:
        self.sent.append(("audio",))

    async def add_message(self, role: Literal["user", "assistant"], text: str) -> None:
        self.sent.append(("message", role, text))

    async def add_tool_result(self, call_id: str, output: str) -> None:
        self.sent.append(("tool_result", call_id, output))

    async def respond(self) -> None:
        self.sent.append(("respond",))

    async def cancel(self) -> None:
        self.sent.append(("cancel",))

    async def update(self, config: VoiceConfig) -> None:
        self.config = config
        self.sent.append(("update", config.instructions))

    async def events(self) -> AsyncIterator[VoiceEvent]:
        return
        yield

    async def response(self) -> AsyncIterator[ResponseEvent]:
        for event in self.script:
            yield event

    async def aclose(self) -> None:
        return None


def _collect(call: VoiceModelCall, messages: list[Message], tools: list[dict[str, Any]] = []) -> list[Any]:
    async def run() -> list[Any]:
        return [e async for e in call.stream("grok:grok-voice-latest", messages, tools)]

    return asyncio.run(run())


def test_heard_turn_is_not_resent_and_response_maps_to_stream_events() -> None:
    session = FakeSession([TextDelta("Sunny "), ToolCall("c1", "get_weather", '{"city":"Paris"}'), ResponseDone(3, 4)])
    session.history.synced = True
    session.history.heard.append("weather in paris")
    messages = [Message(role="system", content="be brief"), Message(role="user", content="weather in paris")]

    events = _collect(VoiceModelCall(session), messages, [{"name": "get_weather"}])

    assert session.sent == [("update", "be brief")]
    assert session.config.tools == ({"name": "get_weather"},)
    assert [e.type for e in events] == ["text_delta", "toolcall_start", "toolcall_arguments", "usage", "done"]
    assert events[1].tool_call_id == "c1" and events[2].delta == '{"city":"Paris"}'
    assert events[3].total_tokens == 7


def test_typed_turn_seeds_history_once_then_asks_for_a_response() -> None:
    session = FakeSession([ResponseDone()])
    messages = [
        Message(role="user", content="hi"),
        Message(role="assistant", content="hello"),
        Message(role="user", content="tapped: Paris"),
    ]

    _collect(VoiceModelCall(session), messages)

    assert session.sent == [
        ("message", "user", "hi"),
        ("message", "assistant", "hello"),
        ("message", "user", "tapped: Paris"),
        ("respond",),
    ]
    assert session.history.synced


def test_tool_results_go_back_as_outputs() -> None:
    session = FakeSession([TextDelta("done"), ResponseDone()])
    session.history.synced = True
    messages = [
        Message(role="user", content="weather"),
        Message(role="assistant", content="", tool_calls=[{"id": "c1"}]),
        Message(role="tool", content="18C", tool_call_id="c1"),
    ]

    _collect(VoiceModelCall(session), messages)

    assert session.sent == [("tool_result", "c1", "18C"), ("respond",)]


def test_failed_response_raises() -> None:
    session = FakeSession([ResponseDone(error="rate limited")])
    session.history.synced = True
    with pytest.raises(RuntimeError, match="rate limited"):
        _collect(VoiceModelCall(session), [Message(role="user", content="hi")])


def test_voice_model_call_only_for_realtime_models_with_an_open_session() -> None:
    assert voice_model_call("grok:grok-4.6", "s1") is None
    with pytest.raises(VoiceSessionNotOpen):
        voice_model_call("grok:grok-voice-latest", "nobody")


Frame = Union[str, bytes]


async def _fake_xai(connection: ServerConnection, received: list[dict[str, Any]], script: list[Frame]) -> None:
    for frame in script:
        await connection.send(frame)
    async for message in connection:
        if isinstance(message, str):
            received.append(json.loads(message))


def _event(payload: dict[str, Any]) -> str:
    return json.dumps(payload)


def test_grok_voice_session_over_the_wire() -> None:
    received: list[dict[str, Any]] = []
    script: list[Frame] = [
        _event({"type": "conversation.item.input_audio_transcription.completed", "transcript": " hi there "}),
        _event({"type": "response.created", "response": {"id": "r1"}}),
        b"\x01\x02",
        _event({"type": "response.output_audio_transcript.delta", "response_id": "r1", "delta": "Hey"}),
        _event({"type": "response.function_call_arguments.done", "response_id": "r1", "call_id": "c1",
                "name": "get_weather", "arguments": "{}"}),
        _event({"type": "response.output_item.done", "response_id": "r1",
                "item": {"type": "function_call", "call_id": "c1", "name": "get_weather", "arguments": "{}"}}),
        _event({"type": "response.done", "response": {"id": "r1", "status": "completed",
                                                       "usage": {"input_tokens": 5, "output_tokens": 2}}}),
        _event({"type": "response.created", "response": {"id": "r2"}}),
        _event({"type": "response.output_audio_transcript.delta", "response_id": "r2", "delta": "stale"}),
    ]

    async def run() -> tuple[list[VoiceEvent], list[ResponseEvent], VoiceSession]:
        async with serve(lambda c: _fake_xai(c, received, script), "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            registry = ModelRegistry()
            registry.register("grok", GrokProvider("key", base_url=f"http://127.0.0.1:{port}/v1"))
            frames: list[str] = []
            config = VoiceConfig(voice="ara", tools=({"name": "get_weather", "parameters": {}},))
            session = await registry.open_voice(
                "grok:grok-voice-latest", config, session_id="s1", observer=lambda d, f: frames.append(d)
            )
            assert voice_model_call("grok:grok-voice-latest", "s1") is not None
            events = session.events()
            seen = [await anext(events), await anext(events)]
            first = [e async for e in session.response()]
            await asyncio.sleep(0.05)
            await session.cancel()
            await session.add_tool_result("c1", "sunny")
            await asyncio.sleep(0.05)
            await registry.close_voice("s1", session)
            assert "received" in frames and "sent" in frames
            return seen, first, session

    seen, first, session = asyncio.run(run())

    assert seen == [UserTranscript("hi there"), AudioDelta(b"\x01\x02")]
    assert session.history.heard == ["hi there"]
    assert first == [TextDelta("Hey"), ToolCall("c1", "get_weather", "{}"), ResponseDone(5, 2)]
    update = received[0]
    assert update["type"] == "session.update"
    assert update["session"]["voice"] == "ara"
    assert update["session"]["tools"] == [{"type": "function", "name": "get_weather", "parameters": {}}]
    assert update["session"]["audio"]["input"]["format"] == {"type": "audio/pcm", "rate": 24000}
    assert [e["type"] for e in received[1:]] == ["response.cancel", "conversation.item.create"]
    with pytest.raises(VoiceSessionNotOpen):
        voice_model_call("grok:grok-voice-latest", "s1")
