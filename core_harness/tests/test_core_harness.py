import asyncio
import os

import httpx
import pytest

from core_ai.providers.openai import OpenAIProvider
from core_ai.registry import ModelRegistry
from core_harness import CoreHarness, NullControlPlane, Tool


def get_weather(city: str, control_plane: NullControlPlane) -> str:
    assert isinstance(control_plane, NullControlPlane)
    return f"It is sunny in {city}."


def call_core_harness() -> tuple[NullControlPlane, object]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("Set OPENAI_API_KEY to run the core harness integration test.")
    if os.getenv("RUN_LIVE_OPENAI_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_OPENAI_TESTS=1 to run the core harness integration test.")

    model_name = os.getenv("OPENAI_TEST_MODEL", "gpt-4o-mini")
    registry = ModelRegistry()
    registry.register(
        "openai",
        OpenAIProvider(
            api_key=api_key,
            base_url="https://api.openai.com/v1",
        ),
    )
    control_plane = NullControlPlane()
    harness = CoreHarness(
        registry=registry,
        model_id=f"openai:{model_name}",
        system_prompt="You are a concise assistant. Always call get_weather for weather questions and then answer with the tool result verbatim.",
        tools=[Tool(get_weather)],
        control_plane=control_plane,
    )

    try:
        result = asyncio.run(harness.run("What is the weather in San Francisco?"))
    except httpx.RequestError as exc:
        pytest.skip(f"OpenAI endpoint unavailable in this environment: {exc}")
    return control_plane, result


def test_core_harness_runs_tool_loop() -> None:
    control_plane, result = call_core_harness()
    assert "San Francisco" in result.output_text
    assert "sunny" in result.output_text.lower()
    assert result.tool_calls[0].name == "get_weather"
    assert result.tool_calls[0].arguments == {"city": "San Francisco"}
    assert result.usage.total_tokens > 0
    event_types = [event.event_type for event in control_plane.events]
    assert event_types[0] == "run_started"
    assert "tool_call_delta" in event_types
    assert "tool_call_started" in event_types
    assert "tool_execution_completed" in event_types
    assert event_types[-1] == "run_completed"
    assert control_plane.events[-1].payload["usage"]["total_tokens"] > 0
