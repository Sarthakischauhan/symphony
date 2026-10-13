"""CoreHarness.submit: interrupt, answer, and mid-run user input."""

from __future__ import annotations

import asyncio
from typing import Any, List

import pytest

from core_ai.types import Message, StreamEvent
from core_harness import (
    Answer,
    CoreHarness,
    EventSink,
    HarnessCancelled,
    HarnessConfig,
    InteractionPort,
    Interrupt,
    Tool,
    UserInput,
)


def _text_turn(text: str = "ok") -> list[StreamEvent]:
    return [
        StreamEvent(type="text_delta", delta=text),
        StreamEvent(type="usage", prompt_tokens=1, completion_tokens=1, total_tokens=2),
        StreamEvent(type="done"),
    ]


def _tool_turn(name: str, call_id: str = "call-1") -> list[StreamEvent]:
    return [
        StreamEvent(type="toolcall_start", content_index=0, tool_call_id=call_id, tool_name=name),
        StreamEvent(type="toolcall_delta", content_index=0, delta="{}"),
        StreamEvent(type="usage", prompt_tokens=1, completion_tokens=1, total_tokens=2),
        StreamEvent(type="done"),
    ]


class ScriptedRegistry:
    """Replays turns. ``on_call`` runs as each model call starts."""

    def __init__(self, turns: List[List[StreamEvent]], on_call: Any = None) -> None:
        self.turns = turns
        self.on_call = on_call
        self.seen: list[list[Message]] = []

    async def stream(self, model_id: str, messages: list[Message], tools: list[dict[str, Any]]):
        del model_id, tools
        call = len(self.seen)
        self.seen.append(list(messages))
        if self.on_call is not None:
            await self.on_call(call)
        for event in self.turns[min(call, len(self.turns) - 1)]:
            yield event


def _harness(registry: ScriptedRegistry, *, tools: list[Tool] | None = None,
             sink: EventSink | None = None) -> tuple[CoreHarness, EventSink]:
    sink = sink or EventSink()
    harness = CoreHarness(
        registry=registry,  # type: ignore[arg-type]
        model_id="fake:ops",
        system_prompt="test",
        config=HarnessConfig(max_turns=4),
        tools=tools or [],
        sink=sink,
    )
    return harness, sink


def _payloads(sink: EventSink, event_type: str) -> list[dict[str, Any]]:
    return [e.payload for e in sink.events if e.event_type == event_type]


def test_ops_without_an_active_run_are_refused() -> None:
    harness, _ = _harness(ScriptedRegistry([_text_turn()]))
    assert harness.submit(Interrupt()) is False
    assert harness.submit(UserInput("hello")) is False
    assert harness.submit(Answer("nobody-asked", "yes")) is False


def test_interrupt_cancels_the_run_and_reports_its_reason() -> None:
    harness: CoreHarness

    async def on_call(call: int) -> None:
        assert harness.submit(Interrupt("user_cancel")) is True
        # A second interrupt is accepted but must not cancel the handler.
        assert harness.submit(Interrupt("again")) is True
        await asyncio.sleep(0)

    harness, sink = _harness(ScriptedRegistry([_text_turn()], on_call))

    with pytest.raises(HarnessCancelled, match="user_cancel"):
        asyncio.run(harness.run("go"))

    assert [p["reason"] for p in _payloads(sink, "run_cancelled")] == ["user_cancel"]
    assert not _payloads(sink, "run_completed")
    assert harness.submit(Interrupt()) is False


def test_bare_task_cancel_still_reports_cancelled() -> None:
    async def scenario() -> EventSink:
        started = asyncio.Event()

        async def on_call(call: int) -> None:
            started.set()
            await asyncio.sleep(10)

        harness, sink = _harness(ScriptedRegistry([_text_turn()], on_call))
        task = asyncio.create_task(harness.run("go"))
        await started.wait()
        task.cancel()
        with pytest.raises(HarnessCancelled):
            await task
        return sink

    sink = asyncio.run(scenario())
    assert [p["reason"] for p in _payloads(sink, "run_cancelled")] == ["cancelled"]


def test_user_input_is_injected_before_the_next_turn() -> None:
    harness: CoreHarness

    def noop() -> str:
        return "done"

    async def on_call(call: int) -> None:
        if call == 0:
            assert harness.submit(UserInput("use metric units")) is True

    registry = ScriptedRegistry([_tool_turn("noop"), _text_turn("final")], on_call)
    harness, sink = _harness(registry, tools=[Tool(noop)])

    result = asyncio.run(harness.run("go"))

    assert result.output_text == "final"
    injected = _payloads(sink, "message_injected")
    assert [(p["source"], p["content"]) for p in injected] == [("user", "use metric units")]
    second_call = [(m.role, m.content) for m in registry.seen[1]]
    assert second_call[-1] == ("user", "use metric units")


def test_user_input_during_the_last_turn_extends_the_run() -> None:
    harness: CoreHarness

    async def on_call(call: int) -> None:
        if call == 0:
            harness.submit(UserInput("one more thing"))

    registry = ScriptedRegistry([_text_turn("first"), _text_turn("second")], on_call)
    harness, sink = _harness(registry)

    result = asyncio.run(harness.run("go"))

    assert len(registry.seen) == 2
    assert result.output_text == "second"
    assert len(_payloads(sink, "run_completed")) == 1
    assert registry.seen[1][-1].content == "one more thing"


def test_answer_resolves_a_question_asked_through_the_port() -> None:
    class AskingPort(InteractionPort):
        async def request_user_input(self, *, question: str, **kwargs: Any) -> str:
            return await self.expect("q-1")

    async def scenario() -> str:
        harness, sink = _harness(ScriptedRegistry([_text_turn()]), sink=EventSink(AskingPort()))
        waiting = asyncio.create_task(sink.interaction.request_user_input(question="Allow?"))
        await asyncio.sleep(0)
        assert harness.submit(Answer("q-1", "Allow once")) is True
        assert harness.submit(Answer("q-1", "Deny")) is False
        return await waiting

    assert asyncio.run(scenario()) == "Allow once"
