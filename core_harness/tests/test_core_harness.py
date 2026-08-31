import asyncio
import json
import os
from pathlib import Path
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
    HarnessConfig,
    InMemoryEventLog,
    InteractiveControlPlane,
    KeepSystemRecentCompactor,
    NullControlPlane,
    PersistingControlPlane,
    Tool,
)
from core_harness.utils.tokens import estimate_prompt_tokens, message_size_breakdown
from core_harness.state import (
    CLEARED_TOOL_RESULT_MARK,
    COMPACTED_CONTEXT_MARK,
    bound_tool_result,
    build_context_report,
    messages_for_model,
    normalize_tool_protocol,
    prune_stale_tool_results,
)


def get_weather(city: str, control_plane: NullControlPlane) -> str:
    assert isinstance(control_plane, NullControlPlane)
    return f"It is sunny in {city}."


def call_tool_a() -> str:
    """Mark that tool A ran in the multi-tool loop."""
    return "tool_a_ok"


def call_tool_b() -> str:
    """Mark that tool B ran in the multi-tool loop."""
    return "tool_b_ok"


def large_tool_result() -> str:
    return "START-" + ("x" * 200) + "-END"


class LargeToolRegistry:
    def __init__(self) -> None:
        self.calls: list[list[Message]] = []

    async def stream(self, model_id: str, messages: list[Message], tools: list[dict[str, Any]]):
        del model_id, tools
        self.calls.append(list(messages))
        if len(self.calls) == 1:
            yield StreamEvent(
                type="toolcall_start",
                content_index=0,
                tool_call_id="call-large",
                tool_name="large_tool_result",
            )
            yield StreamEvent(type="toolcall_delta", content_index=0, delta="{}")
            yield StreamEvent(type="usage", prompt_tokens=1, completion_tokens=1, total_tokens=2)
            yield StreamEvent(type="done", content_index=0)
            return
        yield StreamEvent(type="text_delta", content_index=0, delta="done")
        yield StreamEvent(type="usage", prompt_tokens=1, completion_tokens=1, total_tokens=2)
        yield StreamEvent(type="done", content_index=0)


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


def test_core_harness_forwards_reasoning_effort() -> None:
    class EffortRegistry:
        def __init__(self) -> None:
            self.efforts: list[Optional[str]] = []

        async def stream(
            self,
            model_id: str,
            messages: list[Message],
            tools: list[dict[str, Any]],
            reasoning_effort: Optional[str] = None,
        ):
            del model_id, messages, tools
            self.efforts.append(reasoning_effort)
            yield StreamEvent(type="text_delta", content_index=0, delta="done")
            yield StreamEvent(type="done", content_index=0)

    registry = EffortRegistry()
    harness = CoreHarness(
        registry=registry,  # type: ignore[arg-type]
        model_id="openai:gpt-5.6-luna",
        system_prompt="Be useful.",
        config=HarnessConfig(max_turns=1),
        reasoning_effort="high",
    )

    result = asyncio.run(harness.run("Do it"))

    assert result.output_text == "done"
    assert registry.efforts == ["high"]


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
        config=HarnessConfig(
            context_limits={"fake:test-model": context_limit},
            context_warn_threshold=context_warn_threshold,
            context_compact_threshold=context_compact_threshold,
            compaction_keep_recent=keep_recent,
        ),
        tools=[Tool(get_weather)],
        control_plane=control_plane,
        compactor=(
            KeepSystemRecentCompactor(keep_recent=keep_recent)
            if context_compact_threshold is not None
            else None
        ),
    )
    result = asyncio.run(harness.run("What is the weather in San Francisco?"))
    return registry, control_plane, result


def bulky_result() -> str:
    return "PAYLOAD-" + ("x" * 4000)


class RepeatToolRegistry:
    """Call bulky_result n times, then finish."""

    def __init__(self, n_calls: int = 8) -> None:
        self.n_calls = n_calls
        self.calls: list[list[Message]] = []

    async def stream(self, model_id: str, messages: list[Message], tools: list[dict[str, Any]]):
        del model_id, tools
        self.calls.append(list(messages))
        n_tools = sum(1 for message in messages if message.role == "tool")
        if n_tools < self.n_calls:
            idx = n_tools
            yield StreamEvent(
                type="toolcall_start",
                content_index=0,
                tool_call_id=f"call-{idx}",
                tool_name="bulky_result",
            )
            yield StreamEvent(type="toolcall_delta", content_index=0, delta="{}")
            yield StreamEvent(type="usage", prompt_tokens=8, completion_tokens=2, total_tokens=10)
            yield StreamEvent(type="done", content_index=0)
            return
        yield StreamEvent(type="text_delta", content_index=0, delta="done")
        yield StreamEvent(type="usage", prompt_tokens=8, completion_tokens=2, total_tokens=10)
        yield StreamEvent(type="done", content_index=0)


def _tool_group(
    call_id: str,
    name: str,
    result: str,
    *,
    arguments: Optional[dict[str, Any]] = None,
) -> list[Message]:
    payload = arguments if arguments is not None else {}
    return [
        Message(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(payload)},
                }
            ],
        ),
        Message(role="tool", content=result, tool_call_id=call_id),
    ]


def test_bound_tool_result_keeps_40_60_head_tail() -> None:
    text = "START-" + ("x" * 200) + "-END"
    bounded = bound_tool_result(text, max_chars=80)
    assert len(bounded) == 80
    assert bounded.startswith("START-")
    assert bounded.endswith("-END")
    assert "tool result truncated" in bounded


def test_bound_tool_result_mentions_spill_path() -> None:
    text = "H" * 40 + "M" * 400 + "T" * 60
    bounded = bound_tool_result(
        text,
        max_chars=200,
        spill_path=".symphony/tool_outputs/call-1.txt",
    )
    assert "tool result truncated" in bounded
    assert ".symphony/tool_outputs/call-1.txt" in bounded
    assert "do not re-run" in bounded
    assert bounded.startswith("H")
    assert bounded.endswith("T")


def test_prune_stale_tool_results_stubs_older_and_does_not_mutate() -> None:
    messages = [
        Message(role="system", content="sys"),
        Message(role="user", content="go"),
    ]
    for index in range(4):
        messages.extend(
            _tool_group(
                f"c{index}",
                "read_file",
                "A" * 500,
                arguments={"path": f"src/file{index}.py"},
            )
        )

    original = [message.content for message in messages]
    pruned = prune_stale_tool_results(messages, keep_recent=2)
    assert [message.content for message in messages] == original

    tools = [message for message in pruned if message.role == "tool"]
    assert len(tools) == 4
    assert str(tools[0].content).startswith(CLEARED_TOOL_RESULT_MARK)
    assert "read_file path=src/file0.py" in str(tools[0].content)
    assert "500" in str(tools[0].content)
    assert "already observed" in str(tools[0].content)
    assert str(tools[1].content).startswith(CLEARED_TOOL_RESULT_MARK)
    assert tools[2].content == "A" * 500
    assert tools[3].content == "A" * 500
    assert estimate_prompt_tokens(pruned) < estimate_prompt_tokens(messages)


def test_messages_for_model_stays_linear_until_budget() -> None:
    messages = [
        Message(role="system", content="sys"),
        Message(role="user", content="go"),
    ]
    for index in range(6):
        messages.extend(_tool_group(f"c{index}", "bash", "PAYLOAD-" + ("x" * 200)))

    linear = messages_for_model(messages, keep_recent=2, prune_tokens=None)
    assert [message.content for message in linear if message.role == "tool"] == [
        message.content for message in messages if message.role == "tool"
    ]

    under = messages_for_model(messages, keep_recent=2, prune_tokens=1_000_000)
    assert under == linear

    over = messages_for_model(messages, keep_recent=2, prune_tokens=0)
    tools = [message for message in over if message.role == "tool"]
    stubs = [
        message
        for message in tools
        if str(message.content).startswith(CLEARED_TOOL_RESULT_MARK)
    ]
    full = [message for message in tools if str(message.content).startswith("PAYLOAD-")]
    assert len(stubs) == 4
    assert len(full) == 2


def test_stale_tool_results_stay_until_token_budget() -> None:
    registry = RepeatToolRegistry(n_calls=8)
    harness = CoreHarness(
        registry=registry,  # type: ignore[arg-type]
        model_id="fake:test-model",
        system_prompt="system",
        config=HarnessConfig(
            max_turns=16,
            tool_result_max_chars=4_000,
            tool_result_keep_recent=2,
            tool_result_prune_tokens=None,
        ),
        tools=[Tool(bulky_result)],
    )

    result = asyncio.run(harness.run("inspect files"))

    persisted = [message for message in result.messages if message.role == "tool"]
    assert len(persisted) == 8
    assert all("PAYLOAD-" in str(message.content) for message in persisted)
    last_sent = [message for message in registry.calls[-1] if message.role == "tool"]
    assert len(last_sent) == 8
    assert not any(
        str(message.content).startswith(CLEARED_TOOL_RESULT_MARK)
        for message in last_sent
    )


def test_stale_tool_results_are_pruned_once_over_budget() -> None:
    registry = RepeatToolRegistry(n_calls=8)
    harness = CoreHarness(
        registry=registry,  # type: ignore[arg-type]
        model_id="fake:test-model",
        system_prompt="system",
        config=HarnessConfig(
            max_turns=16,
            tool_result_max_chars=4_000,
            tool_result_keep_recent=2,
            tool_result_prune_tokens=0,
        ),
        tools=[Tool(bulky_result)],
    )

    result = asyncio.run(harness.run("inspect files"))

    persisted = [message for message in result.messages if message.role == "tool"]
    assert len(persisted) == 8
    assert all("PAYLOAD-" in str(message.content) for message in persisted)

    last_sent = [message for message in registry.calls[-1] if message.role == "tool"]
    assert len(last_sent) == 8
    full = [
        message
        for message in last_sent
        if "PAYLOAD-" in str(message.content)
        and not str(message.content).startswith(CLEARED_TOOL_RESULT_MARK)
    ]
    stubs = [
        message
        for message in last_sent
        if str(message.content).startswith(CLEARED_TOOL_RESULT_MARK)
    ]
    assert len(full) == 2
    assert len(stubs) == 6
    assert "already observed" in str(stubs[0].content)
    assert estimate_prompt_tokens(registry.calls[-1]) < estimate_prompt_tokens(result.messages)


def test_build_context_report_splits_stored_and_sent() -> None:
    messages = [
        Message(role="system", content="sys"),
        Message(role="user", content="fix the tpm limit"),
    ]
    for index in range(3):
        messages.extend(_tool_group(f"c{index}", "bash", "B" * 800))

    report = build_context_report(
        messages,
        context_limit=100_000,
        keep_recent_tool_results=1,
        prune_tokens=0,
    )
    assert report.message_count == 8
    assert report.tool_result_count == 3
    assert report.stubbed_result_count == 2
    assert report.sent_tokens < report.stored_tokens
    assert report.utilization is not None
    tool_bucket = next(bucket for bucket in report.buckets if bucket.role == "tool")
    sent_tool = next(bucket for bucket in report.sent_buckets if bucket.role == "tool")
    assert tool_bucket.count == 3
    assert sent_tool.tokens < tool_bucket.tokens
    assert report.messages[-1].stubbed is False
    assert report.messages[-3].stubbed is True


def test_build_context_report_matches_stored_when_under_budget() -> None:
    messages = [
        Message(role="system", content="sys"),
        Message(role="user", content="go"),
    ]
    messages.extend(_tool_group("c0", "bash", "B" * 800))
    report = build_context_report(messages, context_limit=100_000, prune_tokens=None)
    assert report.sent_tokens == report.stored_tokens
    assert report.stubbed_result_count == 0


def test_large_tool_results_are_bounded_before_reentering_context() -> None:
    registry = LargeToolRegistry()
    control_plane = NullControlPlane()
    harness = CoreHarness(
        registry=registry,  # type: ignore[arg-type]
        model_id="fake:test-model",
        system_prompt="system",
        config=HarnessConfig(tool_result_max_chars=80),
        tools=[Tool(large_tool_result)],
        control_plane=control_plane,
    )

    result = asyncio.run(harness.run("run the tool"))

    tool_messages = [message for message in result.messages if message.role == "tool"]
    assert len(tool_messages) == 1
    bounded = str(tool_messages[0].content)
    assert len(bounded) == 80
    assert bounded.startswith("START-")
    assert bounded.endswith("-END")
    assert "tool result truncated" in bounded
    completed = [
        event for event in control_plane.events
        if event.event_type == "tool_execution_completed"
    ]
    assert completed[0].payload["result"] == bounded
    assert completed[0].payload["truncated"] is True
    assert completed[0].payload["original_chars"] == 210
    assert "tool result truncated" in str(registry.calls[1][-1].content)


def test_truncated_tool_results_spill_to_disk(tmp_path: Path) -> None:
    registry = LargeToolRegistry()
    output_dir = tmp_path / ".symphony" / "tool_outputs"
    harness = CoreHarness(
        registry=registry,  # type: ignore[arg-type]
        model_id="fake:test-model",
        system_prompt="system",
        config=HarnessConfig(
            tool_result_max_chars=120,
            tool_output_dir=str(output_dir),
        ),
        tools=[Tool(large_tool_result)],
    )

    result = asyncio.run(harness.run("run the tool"))
    tool_messages = [message for message in result.messages if message.role == "tool"]
    bounded = str(tool_messages[0].content)
    spilled = output_dir / "call-large.txt"
    assert spilled.exists()
    assert spilled.read_text(encoding="utf-8").startswith("START-")
    assert spilled.read_text(encoding="utf-8").endswith("-END")
    assert ".symphony/tool_outputs/call-large.txt" in bounded
    assert "do not re-run" in bounded or "truncated" in bounded


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
    registry = FakeRegistry(prompt_tokens=90)
    control_plane = NullControlPlane()
    harness = CoreHarness(
        registry=registry,  # type: ignore[arg-type]
        model_id="fake:test-model",
        system_prompt="You are a concise assistant.",
        config=HarnessConfig(
            max_turns=8,
            context_limits={"fake:test-model": 100},
            context_compact_threshold=20,
            compaction_keep_recent=2,
        ),
        tools=[Tool(get_weather)],
        control_plane=control_plane,
        compactor=KeepSystemRecentCompactor(keep_recent=2),
    )
    prior = [Message(role="user", content=f"earlier task {index}") for index in range(6)]
    result = asyncio.run(
        harness.run("What is the weather in San Francisco?", conversation=prior)
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
    assert len(registry.calls[1]["messages"]) < len(registry.calls[0]["messages"]) + 2
    assert registry.calls[1]["messages"][0].role == "system"
    assert any(
        message.role == "user" and message.content == "earlier task 0"
        for message in registry.calls[1]["messages"]
    )
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


def test_tool_protocol_normalization_drops_orphans_and_incomplete_groups() -> None:
    messages = [
        Message(role="system", content="system"),
        Message(role="tool", content="orphan", tool_call_id="missing"),
        Message(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "call-a",
                    "type": "function",
                    "function": {"name": "a", "arguments": "{}"},
                },
                {
                    "id": "call-b",
                    "type": "function",
                    "function": {"name": "b", "arguments": "{}"},
                },
            ],
        ),
        Message(role="tool", content="a", tool_call_id="call-a"),
        Message(role="user", content="latest"),
    ]

    normalized = normalize_tool_protocol(messages)
    assert [(message.role, message.content) for message in normalized] == [
        ("system", "system"),
        ("user", "latest"),
    ]


def test_compactor_keeps_complete_tool_group_even_above_message_budget() -> None:
    messages = [
        Message(role="system", content="system"),
        Message(role="user", content="old"),
        Message(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "call-a",
                    "type": "function",
                    "function": {"name": "a", "arguments": "{}"},
                },
                {
                    "id": "call-b",
                    "type": "function",
                    "function": {"name": "b", "arguments": "{}"},
                },
            ],
        ),
        Message(role="tool", content="a", tool_call_id="call-a"),
        Message(role="tool", content="b", tool_call_id="call-b"),
    ]

    compacted = asyncio.run(
        KeepSystemRecentCompactor(keep_recent=2).compact(
            messages,
            turn=0,
            context_limit=100,
            tokens_used=50,
            context_left=50,
        )
    )
    assert [message.role for message in compacted] == [
        "system",
        "user",
        "assistant",
        "tool",
        "tool",
    ]
    assert compacted[1].content == "old"


def test_compactor_pins_original_task_and_summarizes_dropped_turns() -> None:
    messages = [Message(role="system", content="system")]
    messages.append(Message(role="user", content="original task"))
    messages.append(Message(role="assistant", content="ok"))
    for index in range(5):
        messages.append(Message(role="user", content=f"follow-up {index}"))
        messages.append(Message(role="assistant", content=f"ack {index}"))

    compacted = asyncio.run(
        KeepSystemRecentCompactor(keep_recent=3).compact(
            messages,
            turn=0,
            context_limit=8_000,
            tokens_used=400,
            context_left=7_600,
        )
    )
    assert compacted[0].role == "system"
    assert compacted[1].content == "original task"
    assert str(compacted[2].content).startswith(COMPACTED_CONTEXT_MARK)
    assert "follow-up 0" in str(compacted[2].content)
    assert compacted[-2].content == "follow-up 4"
    assert compacted[-1].content == "ack 4"
    assert all(message.content != "follow-up 1" for message in compacted)


def test_compactor_summarizes_dropped_tool_paths() -> None:
    messages = [
        Message(role="system", content="system"),
        Message(role="user", content="original task"),
        Message(role="assistant", content="ok"),
    ]
    for index, path in enumerate(("src/a.py", "src/b.py", "src/c.py")):
        messages.append(Message(role="user", content=f"follow-up {index}"))
        messages.extend(
            _tool_group(
                f"old-{index}",
                "read_file",
                "Z" * 200,
                arguments={"path": path},
            )
        )

    compacted = asyncio.run(
        KeepSystemRecentCompactor(keep_recent=1).compact(
            messages,
            turn=0,
            context_limit=50_000,
            tokens_used=400,
            context_left=40_000,
        )
    )
    assert compacted[1].content == "original task"
    summary = str(compacted[2].content)
    assert summary.startswith(COMPACTED_CONTEXT_MARK)
    assert "src/a.py" in summary
    assert "src/b.py" in summary
    assert "read_file" in summary
    tools = [message for message in compacted if message.role == "tool"]
    assert len(tools) == 1
    assert tools[0].content == "Z" * 200


def test_compactor_prunes_tool_bodies_only_if_still_over_target() -> None:
    messages = [
        Message(role="system", content="system"),
        Message(role="user", content="original task"),
        Message(role="assistant", content="ok"),
        Message(role="user", content="inspect"),
    ]
    messages.extend(
        _tool_group(
            "huge",
            "read_file",
            "Z" * 8000,
            arguments={"path": "src/huge.py"},
        )
    )

    before = estimate_prompt_tokens(messages)
    compacted = asyncio.run(
        KeepSystemRecentCompactor(
            keep_recent=3,
            target_tokens=200,
            keep_recent_tool_results=0,
        ).compact(
            messages,
            turn=0,
            context_limit=50_000,
            tokens_used=before,
            context_left=40_000,
        )
    )
    tools = [message for message in compacted if message.role == "tool"]
    assert len(tools) == 1
    assert str(tools[0].content).startswith(CLEARED_TOOL_RESULT_MARK)
    assert "src/huge.py" in str(tools[0].content)
    assert estimate_prompt_tokens(compacted) < before


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


class ImageEchoRegistry:
    def __init__(self) -> None:
        self.calls: list[list[Message]] = []

    async def stream(self, model_id: str, messages: list[Message], tools: list[dict[str, Any]]):
        del model_id, tools
        self.calls.append(list(messages))
        yield StreamEvent(type="text_delta", content_index=0, delta="seen")
        yield StreamEvent(type="usage", prompt_tokens=12, completion_tokens=1, total_tokens=13)
        yield StreamEvent(type="done", content_index=0)


def test_harness_forwards_multimodal_user_content() -> None:
    registry = ImageEchoRegistry()
    harness = CoreHarness(
        registry=registry,  # type: ignore[arg-type]
        model_id="fake:test-model",
        system_prompt="system",
        config=HarnessConfig(context_limits={"fake:test-model": 1000}),
        tools=[],
    )
    payload = "a" * 20_000
    user_input = [
        {"type": "text", "text": "what is this?"},
        {"type": "image", "media_type": "image/png", "data": payload, "filename": "shot.png"},
    ]

    result = asyncio.run(harness.run(user_input))

    user = [message for message in registry.calls[0] if message.role == "user"][0]
    assert user.content == user_input
    assert result.output_text == "seen"
    sizes = [
        event.payload["context"]["message_sizes"]
        for event in harness.control_plane.events
        if event.event_type == "run_completed"
    ]
    user_tokens = next(item["tokens"] for item in sizes[0] if item["role"] == "user")
    assert user_tokens < 2_000


class ImageToolRegistry:
    def __init__(self) -> None:
        self.calls: list[list[Message]] = []

    async def stream(self, model_id: str, messages: list[Message], tools: list[dict[str, Any]]):
        del model_id, tools
        self.calls.append(list(messages))
        if len(self.calls) == 1:
            yield StreamEvent(
                type="toolcall_start",
                content_index=0,
                tool_call_id="call-image",
                tool_name="look_at_shot",
            )
            yield StreamEvent(type="toolcall_delta", content_index=0, delta="{}")
            yield StreamEvent(type="usage", prompt_tokens=1, completion_tokens=1, total_tokens=2)
            yield StreamEvent(type="done", content_index=0)
            return
        yield StreamEvent(type="text_delta", content_index=0, delta="a cat")
        yield StreamEvent(type="usage", prompt_tokens=1, completion_tokens=1, total_tokens=2)
        yield StreamEvent(type="done", content_index=0)


def look_at_shot() -> list[dict[str, str]]:
    return [
        {"type": "text", "text": "Read image shot.png (image/png, 300 bytes)"},
        {
            "type": "image",
            "media_type": "image/png",
            "data": "a" * 300,
            "filename": "shot.png",
        },
    ]


def test_harness_forwards_image_tool_results_without_dumping_bytes() -> None:
    registry = ImageToolRegistry()
    control_plane = NullControlPlane()
    harness = CoreHarness(
        registry=registry,  # type: ignore[arg-type]
        model_id="fake:test-model",
        system_prompt="system",
        config=HarnessConfig(tool_result_max_chars=80),
        tools=[Tool(look_at_shot)],
        control_plane=control_plane,
    )

    result = asyncio.run(harness.run("look"))

    tool_message = next(message for message in result.messages if message.role == "tool")
    assert isinstance(tool_message.content, list)
    assert tool_message.content[1]["data"] == "a" * 300
    followup = registry.calls[1][-1]
    assert followup.role == "tool"
    assert followup.content[1]["data"] == "a" * 300
    completed = [
        event
        for event in control_plane.events
        if event.event_type == "tool_execution_completed"
    ]
    preview = completed[0].payload["result"]
    assert "Read image shot.png" in preview
    assert "a" * 50 not in preview
    assert result.output_text == "a cat"


def test_control_plane_cancel_stops_harness() -> None:
    registry = FakeRegistry()
    control_plane = InteractiveControlPlane()

    async def _run() -> None:
        await control_plane.send_command(ControlCommand.cancel(reason="stop-now"))
        harness = CoreHarness(
            registry=registry,  # type: ignore[arg-type]
            model_id="fake:test-model",
            system_prompt="You are a concise assistant.",
            config=HarnessConfig(context_limits={"fake:test-model": 100}),
            tools=[Tool(get_weather)],
            control_plane=control_plane,
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
        config=HarnessConfig(
            max_turns=8,
            context_limits={"fake:math-model": 1000},
        ),
        tools=[Tool(call_tool_a), Tool(call_tool_b)],
        control_plane=control_plane,
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
        config=HarnessConfig(),
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
        config=HarnessConfig(max_turns=8),
        tools=[Tool(call_tool_a), Tool(call_tool_b)],
        control_plane=control_plane,
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
