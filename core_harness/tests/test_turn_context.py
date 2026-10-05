"""Per-turn add-on context is sent with the request, never written into system."""

from __future__ import annotations

import asyncio
from typing import Any

from core_ai.types import Message, StreamEvent
from core_harness import Addon, CoreHarness, HarnessConfig, Tool
from core_harness.context import COMPACTED_CONTEXT_MARK
from core_harness.turn_runner import with_turn_context


class ScriptedRegistry:
    def __init__(self, turns: list[list[StreamEvent]]) -> None:
        self.turns = turns
        self.calls: list[list[Message]] = []

    async def stream(self, model_id: str, messages: list[Message], tools: list[dict[str, Any]]):
        del model_id, tools
        self.calls.append([message.model_copy(deep=True) for message in messages])
        for event in self.turns[min(len(self.calls) - 1, len(self.turns) - 1)]:
            yield event


def _usage() -> StreamEvent:
    return StreamEvent(type="usage", prompt_tokens=1, completion_tokens=1, total_tokens=2)


TOOL_TURN = [
    StreamEvent(type="toolcall_start", content_index=0, tool_call_id="call-1", tool_name="ping"),
    StreamEvent(type="toolcall_delta", content_index=0, delta="{}"),
    _usage(),
    StreamEvent(type="done"),
]
TEXT_TURN = [StreamEvent(type="text_delta", delta="done"), _usage(), StreamEvent(type="done")]


class ChangingMemory(Addon):
    """Writes a different memory block on every turn, like a refreshed retrieval."""

    name = "changing_memory"

    def __init__(self) -> None:
        self.turns = 0

    async def before_turn(self, **payload: Any) -> None:
        self.turns += 1
        payload["context"]["memory"] = f"memory block {self.turns}"


def test_system_prefix_is_byte_identical_while_turn_context_changes() -> None:
    def ping() -> str:
        return "pong"

    registry = ScriptedRegistry([TOOL_TURN, TEXT_TURN, TEXT_TURN])
    harness = CoreHarness(
        registry=registry,  # type: ignore[arg-type]
        model_id="fake:test",
        system_prompt="stable system",
        config=HarnessConfig(max_turns=4),
        tools=[Tool(ping)],
        addons=[ChangingMemory()],
    )
    first = asyncio.run(harness.run("task one"))
    asyncio.run(harness.run("task two", conversation=first.messages))

    assert len(registry.calls) == 3
    for index, request in enumerate(registry.calls, start=1):
        assert request[0] == Message(role="system", content="stable system")
        notes = [m for m in request if str(m.content).startswith("memory block")]
        assert [n.content for n in notes] == [f"memory block {index}"]
    # Within a run the note sits before the task, so tool turns only append.
    assert [m.content for m in registry.calls[0]] == ["stable system", "memory block 1", "task one"]
    assert registry.calls[1][1].content == "memory block 2"
    assert registry.calls[1][2].content == "task one"
    # The next run puts the fresh note before the new task and drops the old one.
    assert registry.calls[2][-2].content == "memory block 3"
    assert registry.calls[2][-1].content == "task two"
    # Nothing from the context reaches the conversation that is kept.
    assert all(not str(m.content).startswith("memory block") for m in first.messages)
    assert first.messages[0].content == "stable system"


def test_with_turn_context_placement() -> None:
    system = Message(role="system", content="s")
    task = Message(role="user", content="task")
    compacted = Message(role="user", content=COMPACTED_CONTEXT_MARK + "\nsummary")
    reply = Message(role="assistant", content="ok")
    messages = [system, task, reply, compacted]

    assert with_turn_context(messages, {}) is messages
    assert with_turn_context(messages, {"memory": ""}) is messages
    request = with_turn_context(messages, {"a": "one", "b": "two"})
    assert [m.content for m in request] == ["s", "one\n\ntwo", "task", "ok", compacted.content]
    assert messages == [system, task, reply, compacted]
    assert [m.content for m in with_turn_context([system], {"a": "one"})] == ["s", "one"]
