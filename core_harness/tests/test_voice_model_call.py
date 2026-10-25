import asyncio
from collections.abc import AsyncIterator
from typing import Any, Literal

import pytest

from core_ai.registry import ModelRegistry
from core_ai.types import Message
from core_ai.voice import (
    ResponseDone,
    ResponseEvent,
    TextDelta,
    ToolCall,
    VoiceConfig,
    VoiceEvent,
    VoiceSession,
)
from core_harness import CoreHarness, HarnessConfig, Tool
from core_harness.voice_turns import (
    VoiceLink,
    VoiceModelCall,
    VoiceSessionNotOpen,
    voice_links,
    voice_model_call,
)

MODEL = "grok:grok-voice-latest"


def get_weather(city: str) -> str:
    return f"18C in {city}"


class ScriptedVoice(VoiceSession):
    """One scripted response per model turn; records what the harness sent."""

    def __init__(
        self,
        responses: list[list[ResponseEvent]],
        turn_detection: Literal["server_vad", "manual"] = "server_vad",
    ) -> None:
        self.model_id = "grok-voice-latest"
        self.config = VoiceConfig(voice="eve", turn_detection=turn_detection)
        self.responses = responses
        self.sent: list[str] = []

    async def send_audio(self, audio: bytes) -> None:
        self.sent.append("audio")

    async def add_message(self, role: Literal["user", "assistant"], text: str) -> None:
        self.sent.append(f"{role}:{text}")

    async def add_tool_result(self, call_id: str, output: str) -> None:
        self.sent.append(f"tool:{call_id}:{output}")

    async def respond(self) -> None:
        self.sent.append("respond")

    async def cancel(self) -> None:
        self.sent.append("cancel")

    async def update(self, config: VoiceConfig) -> None:
        self.config = config

    async def events(self) -> AsyncIterator[VoiceEvent]:
        return
        yield

    async def response(self) -> AsyncIterator[ResponseEvent]:
        for event in self.responses.pop(0):
            yield event

    async def aclose(self) -> None:
        return None


def _collect(link: VoiceLink, messages: list[Message], tools: list[dict[str, Any]] = []) -> list[Any]:
    async def run() -> list[Any]:
        return [e async for e in VoiceModelCall(link).stream(MODEL, messages, tools)]

    return asyncio.run(run())


def test_heard_turn_is_not_resent_and_response_maps_to_stream_events() -> None:
    session = ScriptedVoice([[TextDelta("Sunny "), ToolCall("c1", "get_weather", '{"city":"Paris"}'), ResponseDone(3, 4)]])
    link = VoiceLink(MODEL, session, synced=True, heard=["weather in paris"])
    messages = [Message(role="system", content="be brief"), Message(role="user", content="weather in paris")]

    events = _collect(link, messages, [{"name": "get_weather"}])

    assert session.sent == []
    assert link.heard == []
    assert session.config.instructions == "be brief"
    assert session.config.tools == ({"name": "get_weather"},)
    assert [e.type for e in events] == ["text_delta", "toolcall_start", "toolcall_arguments", "usage", "done"]
    assert events[1].tool_call_id == "c1" and events[2].delta == '{"city":"Paris"}'
    assert events[3].total_tokens == 7


def test_typed_turn_seeds_history_once_then_asks_for_a_response() -> None:
    session = ScriptedVoice([[ResponseDone()]])
    link = VoiceLink(MODEL, session)
    messages = [
        Message(role="user", content="hi"),
        Message(role="assistant", content="hello"),
        Message(role="user", content="tapped: Paris"),
    ]

    _collect(link, messages)

    assert link.synced
    assert session.sent == ["user:hi", "assistant:hello", "user:tapped: Paris", "respond"]


def test_failed_response_raises() -> None:
    link = VoiceLink(MODEL, ScriptedVoice([[ResponseDone(error="rate limited")]]), synced=True)
    with pytest.raises(RuntimeError, match="rate limited"):
        _collect(link, [Message(role="user", content="hi")])


def test_voice_model_call_only_for_the_open_links_model() -> None:
    link = voice_links.open("s1", MODEL, ScriptedVoice([]))
    try:
        assert voice_model_call("grok:grok-4.6", "s1") is None
        assert voice_model_call(MODEL, "s1") is not None
        with pytest.raises(VoiceSessionNotOpen):
            voice_model_call(MODEL, "nobody")
    finally:
        voice_links.close("s1", link)
    assert voice_links.get("s1") is None


def test_realtime_model_runs_through_the_open_voice_link() -> None:
    session = ScriptedVoice(
        [
            [ToolCall("c1", "get_weather", '{"city": "Paris"}'), ResponseDone()],
            [TextDelta("It is 18C in Paris."), ResponseDone()],
        ]
    )
    link = voice_links.open("voice-1", MODEL, session)
    link.synced = True
    link.heard.append("weather in Paris?")
    harness = CoreHarness(
        registry=ModelRegistry(),
        model_id=MODEL,
        system_prompt="Be brief.",
        config=HarnessConfig(max_turns=4),
        tools=[Tool(get_weather)],
    )
    try:
        result = asyncio.run(harness.run("weather in Paris?", session_id="voice-1"))
    finally:
        voice_links.close("voice-1", link)

    assert result.output_text == "It is 18C in Paris."
    assert session.sent == ["tool:c1:18C in Paris", "respond"]
    assert session.config.instructions == "Be brief."
    assert [t["name"] for t in session.config.tools] == ["get_weather"]


def test_tool_category_is_a_typed_field() -> None:
    assert Tool(get_weather, category="search").category == "search"
    assert Tool(get_weather).category is None
