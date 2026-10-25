import asyncio
from collections.abc import AsyncIterator
from typing import Literal

from core_ai.registry import ModelRegistry
from core_ai.voice import (
    ResponseDone,
    ResponseEvent,
    TextDelta,
    ToolCall,
    VoiceConfig,
    VoiceEvent,
    VoiceHistory,
    VoiceSession,
    voice_sessions,
)
from core_harness import CoreHarness, HarnessConfig, Tool


def get_weather(city: str) -> str:
    return f"18C in {city}"


class ScriptedVoice(VoiceSession):
    """One scripted response per model turn; records what the harness sent."""

    def __init__(self, responses: list[list[ResponseEvent]]) -> None:
        self.model_id = "grok-voice-latest"
        self.config = VoiceConfig(voice="eve")
        self.history = VoiceHistory()
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


def test_realtime_model_runs_through_the_open_voice_session() -> None:
    session = ScriptedVoice(
        [
            [ToolCall("c1", "get_weather", '{"city": "Paris"}'), ResponseDone()],
            [TextDelta("It is 18C in Paris."), ResponseDone()],
        ]
    )
    session.history.synced = True
    session.history.heard.append("weather in Paris?")
    voice_sessions.register("voice-1", session)
    harness = CoreHarness(
        registry=ModelRegistry(),
        model_id="grok:grok-voice-latest",
        system_prompt="Be brief.",
        config=HarnessConfig(max_turns=4),
        tools=[Tool(get_weather)],
    )
    try:
        result = asyncio.run(harness.run("weather in Paris?", session_id="voice-1"))
    finally:
        voice_sessions.unregister("voice-1", session)

    assert result.output_text == "It is 18C in Paris."
    assert session.sent == ["tool:c1:18C in Paris", "respond"]
    assert session.config.instructions == "Be brief."
    assert [t["name"] for t in session.config.tools] == ["get_weather"]


def test_tool_category_is_a_typed_field() -> None:
    assert Tool(get_weather, category="search").category == "search"
    assert Tool(get_weather).category is None
