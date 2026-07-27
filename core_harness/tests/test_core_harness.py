import asyncio
from typing import Any

from core_ai.types import Message, StreamEvent
from core_harness import CoreHarness, NullControlPlane, Tool


class FakeRegistry:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def stream(
        self,
        model_id: str,
        messages: list[Message],
        tools: list[dict[str, Any]],
    ):
        self.calls.append(
            {
                "model_id": model_id,
                "messages": messages,
                "tools": tools,
            }
        )

        if len(self.calls) == 1:
            yield StreamEvent(
                type="toolcall_start",
                content_index=0,
                tool_call_id="call-weather",
                tool_name="get_weather",
            )
            yield StreamEvent(
                type="toolcall_delta",
                content_index=0,
                delta='{"city": "San Francisco"}',
            )
            yield StreamEvent(
                type="usage",
                prompt_tokens=10,
                completion_tokens=2,
                total_tokens=12,
            )
            yield StreamEvent(type="done", content_index=0)
            return

        yield StreamEvent(
            type="text_delta",
            content_index=0,
            delta="It is sunny in San Francisco.",
        )
        yield StreamEvent(
            type="usage",
            prompt_tokens=20,
            completion_tokens=6,
            total_tokens=26,
        )
        yield StreamEvent(type="done", content_index=0)


def get_weather(city: str, control_plane: NullControlPlane) -> str:
    """Return weather for a city."""
    assert isinstance(control_plane, NullControlPlane)
    return f"It is sunny in {city}."


def call_core_harness() -> tuple[FakeRegistry, NullControlPlane, Any]:
    registry = FakeRegistry()
    control_plane = NullControlPlane()
    harness = CoreHarness(
        registry=registry,
        model_id="fake:test-model",
        system_prompt="You are a concise assistant.",
        tools=[Tool(get_weather)],
        control_plane=control_plane,
        context_limits={"fake:test-model": 100},
    )

    result = asyncio.run(harness.run("What is the weather in San Francisco?"))
    return registry, control_plane, result


def test_core_harness_runs_tool_loop() -> None:
    registry, control_plane, result = call_core_harness()

    assert result.output_text == "It is sunny in San Francisco."
    assert len(registry.calls) == 2
    assert registry.calls[0]["messages"][0].role == "system"
    assert registry.calls[0]["messages"][0].content == "You are a concise assistant."
    assert registry.calls[0]["tools"][0]["name"] == "get_weather"
    assert result.tool_calls[0].name == "get_weather"
    assert result.tool_calls[0].arguments == {"city": "San Francisco"}
    assert result.usage.total_tokens == 38
    assert result.context_limit == 100
    assert result.context_left == 80

    event_types = [event.event_type for event in control_plane.events]
    assert event_types == [
        "run_started",
        "turn_started",
        "tool_call_started",
        "usage",
        "turn_completed",
        "context",
        "tool_execution_started",
        "tool_execution_completed",
        "turn_started",
        "text_delta",
        "usage",
        "turn_completed",
        "context",
        "run_completed",
    ]
    assert control_plane.events[3].payload["cumulative_tokens"] == 12
    assert control_plane.events[12].payload["context_left"] == 80
    assert control_plane.events[-1].payload["usage"]["total_tokens"] == 38
