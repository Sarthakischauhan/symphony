"""EventSink fan-out and the interaction port."""

from __future__ import annotations

import asyncio
from typing import Any

from core_harness import EventSink, InteractionPort


def test_emit_delivers_then_notifies_listeners() -> None:
    order: list[str] = []

    class Sink(EventSink):
        async def deliver(self, event_type: str, payload: dict[str, Any]) -> None:
            order.append(f"deliver:{event_type}")

    sink = Sink()
    seen: list[tuple[str, dict[str, Any]]] = []

    def listener(event_type: str, payload: dict[str, Any]) -> None:
        order.append(f"notify:{event_type}")
        seen.append((event_type, payload))

    sink.subscribe(listener)
    asyncio.run(sink.emit("run_started", {"prompt": "hi"}))

    assert order == ["deliver:run_started", "notify:run_started"]
    assert seen == [("run_started", {"prompt": "hi"})]


def test_unsubscribe_stops_delivery_and_is_idempotent() -> None:
    sink = EventSink()
    seen: list[str] = []
    unsubscribe = sink.subscribe(lambda event_type, payload: seen.append(event_type))

    asyncio.run(sink.emit("run_started"))
    unsubscribe()
    unsubscribe()
    asyncio.run(sink.emit("run_completed"))

    assert seen == ["run_started"]
    assert [event.event_type for event in sink.events] == ["run_started", "run_completed"]


def test_failing_listener_does_not_fail_emit_or_other_listeners() -> None:
    sink = EventSink()
    seen: list[str] = []

    def broken(event_type: str, payload: dict[str, Any]) -> None:
        raise RuntimeError("listener bug")

    sink.subscribe(broken)
    sink.subscribe(lambda event_type, payload: seen.append(event_type))
    asyncio.run(sink.emit("run_completed"))

    assert seen == ["run_completed"]
    assert len(sink.events) == 1


def test_default_interaction_has_no_human_and_returns_default() -> None:
    sink = EventSink()
    answer = asyncio.run(
        sink.interaction.request_user_input(question="Proceed?", default="yes")
    )
    assert answer == "yes"
    assert not hasattr(sink, "request_user_input")


def test_sink_uses_the_interaction_port_it_is_given() -> None:
    class Human(InteractionPort):
        async def request_user_input(self, *, question: str, **kwargs: Any) -> str:
            return f"answered {question}"

    sink = EventSink(Human())
    assert asyncio.run(sink.interaction.request_user_input(question="q")) == "answered q"


def test_human_interaction_asks_through_the_event_stream() -> None:
    from core_harness import HumanInteraction

    async def scenario() -> tuple[str, EventSink]:
        sink = EventSink()
        sink.interaction = HumanInteraction(sink)
        waiting = asyncio.create_task(sink.interaction.request_user_input(
            question="Allow bash?", choices=["Allow once", "Deny"], kind="approval",
            metadata={"tool_name": "bash"},
        ))
        await asyncio.sleep(0)
        (asked,) = [event.payload for event in sink.events if event.event_type == "question_asked"]
        assert asked["question"] == "Allow bash?"
        assert asked["choices"] == ["Allow once", "Deny"]
        assert asked["kind"] == "approval" and asked["tool_name"] == "bash"
        assert sink.interaction.answer(asked["request_id"], "Deny") is True
        return await waiting, sink

    answer, sink = asyncio.run(scenario())
    assert answer == "Deny"
    assert not sink.interaction.pending


def test_forked_human_interaction_is_answered_through_the_parent() -> None:
    from core_harness import HumanInteraction

    async def scenario() -> str:
        parent, child = EventSink(), EventSink()
        parent.interaction = HumanInteraction(parent)
        child.interaction = parent.interaction.fork(child)
        waiting = asyncio.create_task(child.interaction.request_user_input(question="child?"))
        await asyncio.sleep(0)
        assert not parent.events
        (asked,) = child.events
        parent.interaction.answer(asked.payload["request_id"], "yes")
        return await waiting

    assert asyncio.run(scenario()) == "yes"
