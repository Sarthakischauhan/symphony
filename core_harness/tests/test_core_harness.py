import asyncio
import os
from typing import Any, Optional

import httpx
import pytest

from core_ai.providers.openai import OpenAIProvider
from core_ai.registry import ModelRegistry
from core_ai.types import Message, StreamEvent
from core_harness import (
    ControlCommand,
    ControlPlaneEventType,
    CoreHarness,
    FanoutControlPlane,
    HarnessCancelled,
    InMemoryEventLog,
    InteractiveControlPlane,
    KeepSystemRecentCompactor,
    NullControlPlane,
    PersistingControlPlane,
    Tool,
)
from core_harness.tokens import estimate_prompt_tokens, message_size_breakdown


def get_weather(city: str, control_plane: NullControlPlane) -> str:
    assert isinstance(control_plane, NullControlPlane)
    return f"It is sunny in {city}."


def call_tool_a() -> str:
    """Mark that tool A ran in the multi-tool loop."""
    return "tool_a_ok"


def call_tool_b() -> str:
    """Mark that tool B ran in the multi-tool loop."""
    return "tool_b_ok"


class FakeRegistry:
    def __init__(self, *, emit_usage: bool = True, prompt_tokens: int = 10) -> None:
        self.calls: list[dict[str, Any]] = []
        self.emit_usage = emit_usage
        self.prompt_tokens = prompt_tokens

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
            if self.emit_usage:
                yield StreamEvent(
                    type="usage",
                    prompt_tokens=self.prompt_tokens,
                    completion_tokens=2,
                    total_tokens=self.prompt_tokens + 2,
                )
            yield StreamEvent(type="done", content_index=0)
            return

        yield StreamEvent(
            type="text_delta",
            content_index=0,
            delta="It is sunny in San Francisco.",
        )
        if self.emit_usage:
            yield StreamEvent(
                type="usage",
                prompt_tokens=self.prompt_tokens + 10,
                completion_tokens=6,
                total_tokens=self.prompt_tokens + 16,
            )
        yield StreamEvent(type="done", content_index=0)


class TwoToolLoopRegistry:
    """Deterministic registry: call_tool_a → call_tool_b → answer 15."""

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
                "messages": list(messages),
                "tools": tools,
            }
        )
        tool_names = {tool["name"] for tool in tools}
        assert tool_names == {"call_tool_a", "call_tool_b"}

        completed = {
            message.tool_call_id
            for message in messages
            if message.role == "tool" and message.tool_call_id
        }

        if "call-a" not in completed:
            yield StreamEvent(
                type="toolcall_start",
                content_index=0,
                tool_call_id="call-a",
                tool_name="call_tool_a",
            )
            yield StreamEvent(
                type="toolcall_delta",
                content_index=0,
                delta="{}",
            )
            yield StreamEvent(
                type="usage",
                prompt_tokens=12,
                completion_tokens=3,
                total_tokens=15,
            )
            yield StreamEvent(type="done", content_index=0)
            return

        if "call-b" not in completed:
            yield StreamEvent(
                type="toolcall_start",
                content_index=0,
                tool_call_id="call-b",
                tool_name="call_tool_b",
            )
            yield StreamEvent(
                type="toolcall_delta",
                content_index=0,
                delta="{}",
            )
            yield StreamEvent(
                type="usage",
                prompt_tokens=18,
                completion_tokens=3,
                total_tokens=21,
            )
            yield StreamEvent(type="done", content_index=0)
            return

        yield StreamEvent(type="text_delta", content_index=0, delta="15")
        yield StreamEvent(
            type="usage",
            prompt_tokens=24,
            completion_tokens=1,
            total_tokens=25,
        )
        yield StreamEvent(type="done", content_index=0)


def call_fake_harness(
    *,
    emit_usage: bool = True,
    prompt_tokens: int = 10,
    context_limit: int = 100,
    context_warn_threshold: Optional[int] = None,
    context_compact_threshold: Optional[int] = None,
    keep_recent: int = 2,
) -> tuple[FakeRegistry, NullControlPlane, Any]:
    registry = FakeRegistry(emit_usage=emit_usage, prompt_tokens=prompt_tokens)
    control_plane = NullControlPlane()
    harness = CoreHarness(
        registry=registry,  # type: ignore[arg-type]
        model_id="fake:test-model",
        system_prompt="You are a concise assistant.",
        tools=[Tool(get_weather)],
        control_plane=control_plane,
        context_limits={"fake:test-model": context_limit},
        context_warn_threshold=context_warn_threshold,
        context_compact_threshold=context_compact_threshold,
        compactor=(
            KeepSystemRecentCompactor(keep_recent=keep_recent)
            if context_compact_threshold is not None
            else None
        ),
    )
    result = asyncio.run(harness.run("What is the weather in San Francisco?"))
    return registry, control_plane, result


def test_core_harness_runs_tool_loop_with_usage_and_context() -> None:
    registry, control_plane, result = call_fake_harness(prompt_tokens=10, context_limit=100)

    assert result.output_text == "It is sunny in San Francisco."
    assert len(registry.calls) == 2
    assert registry.calls[0]["messages"][0].role == "system"
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
        "tool_call_delta",
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
    usage_events = [event for event in control_plane.events if event.event_type == "usage"]
    assert usage_events[0].payload["cumulative_tokens"] == 12
    assert usage_events[0].payload["estimated"] is False
    context_events = [event for event in control_plane.events if event.event_type == "context"]
    assert context_events[0].payload["context_left"] == 90
    assert context_events[1].payload["context_left"] == 80
    assert "message_sizes" in context_events[0].payload
    assert context_events[0].payload["message_sizes"][0]["role"] == "system"
    assert control_plane.events[-1].payload["usage"]["total_tokens"] == 38


def test_core_harness_estimates_usage_when_provider_omits_it() -> None:
    _, control_plane, result = call_fake_harness(emit_usage=False, context_limit=10_000)

    usage_events = [event for event in control_plane.events if event.event_type == "usage"]
    assert len(usage_events) == 2
    assert all(event.payload["estimated"] is True for event in usage_events)
    assert usage_events[0].payload["prompt_tokens"] > 0
    assert usage_events[0].payload["completion_tokens"] > 0
    assert result.usage.total_tokens == sum(
        event.payload["total_tokens"] for event in usage_events
    )
    assert result.context_left is not None


def test_core_harness_emits_context_warning_below_threshold() -> None:
    _, control_plane, result = call_fake_harness(
        prompt_tokens=90,
        context_limit=100,
        context_warn_threshold=15,
    )

    event_types = [event.event_type for event in control_plane.events]
    assert "context_warning" in event_types
    warning = next(
        event for event in control_plane.events if event.event_type == "context_warning"
    )
    assert warning.payload["threshold"] == 15
    assert warning.payload["context_left"] == 10
    assert result.context_left == 0


def test_core_harness_compacts_when_context_left_is_low() -> None:
    registry, control_plane, result = call_fake_harness(
        prompt_tokens=90,
        context_limit=100,
        context_compact_threshold=20,
        keep_recent=2,
    )

    event_types = [event.event_type for event in control_plane.events]
    assert "compaction_started" in event_types
    assert "compaction_completed" in event_types
    compact_index = event_types.index("compaction_started")
    assert event_types[compact_index : compact_index + 2] == [
        "compaction_started",
        "compaction_completed",
    ]
    first_turn = event_types.index("turn_started")
    second_turn = event_types.index("turn_started", first_turn + 1)
    assert first_turn < compact_index < second_turn

    completed = next(
        event for event in control_plane.events if event.event_type == "compaction_completed"
    )
    assert completed.payload["message_count_after"] < completed.payload["message_count_before"]
    assert completed.payload["estimated_tokens_after"] <= completed.payload[
        "estimated_tokens_before"
    ]
    assert len(registry.calls[1]["messages"]) < len(registry.calls[0]["messages"]) + 2
    assert registry.calls[1]["messages"][0].role == "system"
    assert result.output_text == "It is sunny in San Francisco."


def test_message_size_breakdown_accounts_per_message() -> None:
    messages = [
        Message(role="system", content="You are helpful."),
        Message(role="user", content="Hello there"),
    ]
    sizes = message_size_breakdown(messages)
    assert [entry["role"] for entry in sizes] == ["system", "user"]
    assert all(entry["tokens"] >= 1 for entry in sizes)
    assert estimate_prompt_tokens(messages) == sum(entry["tokens"] for entry in sizes)


def test_control_plane_fanout_and_event_log() -> None:
    primary = NullControlPlane()
    event_log = InMemoryEventLog()
    plane = FanoutControlPlane(
        [primary, PersistingControlPlane(event_log)],
    )

    async def _emit() -> None:
        await plane.emit(ControlPlaneEventType.RUN_STARTED, {"model_id": "fake:test"})
        await plane.emit("usage", {"turn": 0, "total_tokens": 3})

    asyncio.run(_emit())
    assert [event.event_type for event in primary.events] == ["run_started", "usage"]
    assert [event.event_type for event in event_log.events] == ["run_started", "usage"]
    assert event_log.events[0].payload["model_id"] == "fake:test"


def test_control_plane_cancel_stops_harness() -> None:
    registry = FakeRegistry()
    control_plane = InteractiveControlPlane()

    async def _run() -> None:
        await control_plane.send_command(ControlCommand.cancel(reason="stop-now"))
        harness = CoreHarness(
            registry=registry,  # type: ignore[arg-type]
            model_id="fake:test-model",
            system_prompt="You are a concise assistant.",
            tools=[Tool(get_weather)],
            control_plane=control_plane,
            context_limits={"fake:test-model": 100},
        )
        await harness.run("What is the weather in San Francisco?")

    with pytest.raises(HarnessCancelled, match="stop-now"):
        asyncio.run(_run())
    assert control_plane.events[0].event_type == "run_started"
    assert control_plane.events[-1].event_type == "run_cancelled"
    assert control_plane.events[-1].payload["reason"] == "stop-now"
    assert len(registry.calls) == 0


def test_e2e_two_tool_loop_answers_three_times_five() -> None:
    """Full loop: call_tool_a → call_tool_b → answer 3 * 5 as a number only."""
    registry = TwoToolLoopRegistry()
    event_log = InMemoryEventLog()
    recorder = NullControlPlane()
    control_plane = InteractiveControlPlane(
        event_log=event_log,
        subscribers=[recorder],
    )
    harness = CoreHarness(
        registry=registry,  # type: ignore[arg-type]
        model_id="fake:math-model",
        system_prompt=(
            "You must call call_tool_a, then call call_tool_b, then answer "
            "3 * 5 with only the number."
        ),
        tools=[Tool(call_tool_a), Tool(call_tool_b)],
        control_plane=control_plane,
        context_limits={"fake:math-model": 1000},
        max_turns=8,
    )

    result = asyncio.run(
        harness.run("Call both tools in order, then answer 3 * 5 only in number.")
    )

    assert result.output_text.strip() == "15"
    assert [tool_call.name for tool_call in result.tool_calls] == [
        "call_tool_a",
        "call_tool_b",
    ]
    assert result.tool_calls[0].arguments == {}
    assert result.tool_calls[1].arguments == {}
    assert len(registry.calls) == 3
    assert result.usage.total_tokens == 61

    event_types = [event.event_type for event in control_plane.events]
    assert event_types[0] == ControlPlaneEventType.RUN_STARTED.value
    assert event_types.count("tool_execution_completed") == 2
    assert event_types[-1] == ControlPlaneEventType.RUN_COMPLETED.value

    completed_tools = [
        event.payload["tool_name"]
        for event in control_plane.events
        if event.event_type == "tool_execution_completed"
    ]
    assert completed_tools == ["call_tool_a", "call_tool_b"]
    assert control_plane.events[-1].payload["output_text"] == "15"

    logged_types = [event.event_type for event in event_log.events]
    assert logged_types == event_types
    assert [event.event_type for event in recorder.events] == event_types


def call_live_core_harness() -> tuple[NullControlPlane, object]:
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
        system_prompt=(
            "You are a concise assistant. Always call get_weather for weather "
            "questions and then answer with the tool result verbatim."
        ),
        tools=[Tool(get_weather)],
        control_plane=control_plane,
    )

    try:
        result = asyncio.run(harness.run("What is the weather in San Francisco?"))
    except httpx.RequestError as exc:
        pytest.skip(f"OpenAI endpoint unavailable in this environment: {exc}")
    return control_plane, result


def call_live_two_tool_math_harness() -> tuple[InteractiveControlPlane, object]:
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
    event_log = InMemoryEventLog()
    control_plane = InteractiveControlPlane(event_log=event_log)
    harness = CoreHarness(
        registry=registry,
        model_id=f"openai:{model_name}",
        system_prompt=(
            "You are a careful tool-using assistant. You MUST call call_tool_a first, "
            "then call call_tool_b, and only after both tools have returned should you "
            "answer the arithmetic. Final answer must be only the number for 3 * 5."
        ),
        tools=[Tool(call_tool_a), Tool(call_tool_b)],
        control_plane=control_plane,
        max_turns=8,
    )

    try:
        result = asyncio.run(
            harness.run(
                "Call call_tool_a, then call_tool_b, then answer 3 * 5 only in number."
            )
        )
    except httpx.RequestError as exc:
        pytest.skip(f"OpenAI endpoint unavailable in this environment: {exc}")
    return control_plane, result


def test_core_harness_runs_tool_loop() -> None:
    control_plane, result = call_live_core_harness()
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
    assert "context" in event_types
    assert event_types[-1] == "run_completed"
    assert control_plane.events[-1].payload["usage"]["total_tokens"] > 0
    assert "message_sizes" in control_plane.events[-1].payload["context"]


def test_e2e_live_two_tool_loop_answers_three_times_five() -> None:
    control_plane, result = call_live_two_tool_math_harness()
    assert result.output_text.strip() == "15"
    tool_names = [tool_call.name for tool_call in result.tool_calls]
    assert tool_names == ["call_tool_a", "call_tool_b"]
    event_types = [event.event_type for event in control_plane.events]
    assert event_types[0] == "run_started"
    assert event_types[-1] == "run_completed"
    completed_tools = [
        event.payload["tool_name"]
        for event in control_plane.events
        if event.event_type == "tool_execution_completed"
    ]
    assert completed_tools == ["call_tool_a", "call_tool_b"]
    assert control_plane.event_log is not None
    assert len(asyncio.run(control_plane.event_log.list_events())) == len(
        control_plane.events
    )
