"""Parent/child agent spawning through the shared control plane."""

from __future__ import annotations

import asyncio
from typing import Any

from core_ai.types import Message, StreamEvent
from core_harness import CoreHarness, NullControlPlane, Tool
from core_harness.harness import SUBAGENT_SYSTEM_PROMPT


class ScriptedRegistry:
    def __init__(self, turns: list[list[StreamEvent]]) -> None:
        self.turns = turns
        self.calls: list[dict[str, Any]] = []

    async def stream(self, model_id: str, messages: list[Message], tools: list[dict[str, Any]]):
        self.calls.append(
            {"model_id": model_id, "messages": list(messages), "tools": tools}
        )
        events = self.turns[min(len(self.calls) - 1, len(self.turns) - 1)]
        for event in events:
            yield event


def _tool_turn(name: str, arguments: str, call_id: str = "call-1") -> list[StreamEvent]:
    return [
        StreamEvent(type="toolcall_start", content_index=0, tool_call_id=call_id, tool_name=name),
        StreamEvent(type="toolcall_delta", content_index=0, delta=arguments),
        StreamEvent(type="usage", prompt_tokens=1, completion_tokens=1, total_tokens=2),
        StreamEvent(type="done"),
    ]


def _text_turn(text: str) -> list[StreamEvent]:
    return [
        StreamEvent(type="text_delta", delta=text),
        StreamEvent(type="usage", prompt_tokens=1, completion_tokens=1, total_tokens=2),
        StreamEvent(type="done"),
    ]


def inspect_repo(path: str) -> str:
    return f"contents of {path}"


def test_run_events_carry_agent_id_without_parent() -> None:
    registry = ScriptedRegistry([_text_turn("hello")])
    plane = NullControlPlane()
    harness = CoreHarness(
        registry=registry,  # type: ignore[arg-type]
        model_id="fake:test-model",
        system_prompt="parent",
        control_plane=plane,
        agent_id="parent-agent",
    )
    result = asyncio.run(harness.run("hi"))
    assert result.output_text == "hello"
    assert all(event.payload["agent_id"] == "parent-agent" for event in plane.events)
    assert all(event.payload["parent_id"] is None for event in plane.events)


def test_spawn_emits_parent_and_child_identity() -> None:
    registry = ScriptedRegistry(
        [
            _tool_turn(
                "spawn_agent",
                '{"prompt": "Inspect README.md", "label": "inspect readme"}',
                "spawn-1",
            ),
            _tool_turn("inspect_repo", '{"path": "README.md"}', "child-tool"),
            _text_turn("README is the project intro."),
            _text_turn("The child found that README is the project intro."),
        ]
    )
    plane = NullControlPlane()
    harness = CoreHarness(
        registry=registry,  # type: ignore[arg-type]
        model_id="fake:test-model",
        system_prompt="parent",
        tools=[Tool(inspect_repo)],
        control_plane=plane,
        agent_id="parent-agent",
        max_turns=4,
    )
    harness.register_tool(harness.make_spawn_tool())

    result = asyncio.run(harness.run("Inspect the repo via a subagent."))

    types = [event.event_type for event in plane.events]
    assert "agent_spawned" in types
    assert "agent_completed" in types
    spawned = next(event for event in plane.events if event.event_type == "agent_spawned")
    completed = next(event for event in plane.events if event.event_type == "agent_completed")
    child_id = spawned.payload["child_id"]
    assert spawned.payload["agent_id"] == "parent-agent"
    assert spawned.payload["parent_id"] is None
    assert spawned.payload["label"] == "inspect readme"
    assert completed.payload["child_id"] == child_id
    assert "project intro" in completed.payload["output_text"]

    child_events = [event for event in plane.events if event.payload.get("agent_id") == child_id]
    assert child_events
    assert all(event.payload["parent_id"] == "parent-agent" for event in child_events)
    assert any(event.event_type == "run_started" for event in child_events)
    assert any(event.event_type == "run_completed" for event in child_events)
    assert any(
        event.event_type == "tool_execution_completed"
        and event.payload.get("tool_name") == "inspect_repo"
        for event in child_events
    )

    child_calls = [call for call in registry.calls if any(
        message.role == "system" and SUBAGENT_SYSTEM_PROMPT in str(message.content)
        for message in call["messages"]
    )]
    assert child_calls
    child_tool_names = {tool["name"] for tool in child_calls[0]["tools"]}
    assert "inspect_repo" in child_tool_names
    assert "spawn_agent" not in child_tool_names

    tool_results = [
        str(message.content)
        for message in result.messages
        if message.role == "tool"
    ]
    assert any("Subagent inspect readme completed." in text for text in tool_results)
    assert "project intro" in result.output_text


def test_spawn_depth_limit_returns_error_without_child_run() -> None:
    registry = ScriptedRegistry([_text_turn("should not run")])
    plane = NullControlPlane()
    harness = CoreHarness(
        registry=registry,  # type: ignore[arg-type]
        model_id="fake:test-model",
        system_prompt="parent",
        control_plane=plane,
        agent_id="parent-agent",
        spawn_depth=1,
        max_spawn_depth=1,
    )
    result = asyncio.run(harness.spawn("go deeper", label="too deep"))
    assert result.output_text.startswith("error: spawn depth")
    assert [event.event_type for event in plane.events] == ["agent_failed"]
    assert registry.calls == []


def test_direct_spawn_uses_shared_control_plane() -> None:
    registry = ScriptedRegistry([_text_turn("isolated answer")])
    plane = NullControlPlane()
    harness = CoreHarness(
        registry=registry,  # type: ignore[arg-type]
        model_id="fake:test-model",
        system_prompt="parent",
        control_plane=plane,
        agent_id="parent-agent",
        session_id="session-parent",
    )
    result = asyncio.run(harness.spawn("do the work", label="worker"))
    assert result.output_text == "isolated answer"
    spawned = next(event for event in plane.events if event.event_type == "agent_spawned")
    child_id = spawned.payload["child_id"]
    child_events = [event for event in plane.events if event.payload.get("agent_id") == child_id]
    assert child_events[0].event_type == "run_started"
    assert child_events[0].payload["parent_id"] == "parent-agent"
    assert child_events[-1].event_type == "run_completed"
