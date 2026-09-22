"""Wire stamps on harness events: started_at / ended_at / duration_ms."""

from __future__ import annotations

import asyncio
from typing import Any, List

import pytest

from core_ai.types import Message, StreamEvent
from core_harness import (
    ControlPlaneEventType,
    CoreHarness,
    HarnessCancelled,
    HarnessConfig,
    EventSink,
    Tool,
)
from core_harness.timing import duration_human, duration_ms, with_ended, with_started


class ScriptedRegistry:
    def __init__(self, turns: List[List[StreamEvent]]) -> None:
        self.turns = turns
        self.calls = 0

    async def stream(self, model_id: str, messages: list[Message], tools: list[dict[str, Any]]):
        del model_id, messages, tools
        events = self.turns[min(self.calls, len(self.turns) - 1)]
        self.calls += 1
        for event in events:
            yield event


def echo(text: str = "") -> str:
    return f"echo:{text}"


def _tool_turn(name: str, arguments: str = "{}", call_id: str = "call-1") -> list[StreamEvent]:
    return [
        StreamEvent(type="toolcall_start", content_index=0, tool_call_id=call_id, tool_name=name),
        StreamEvent(type="toolcall_delta", content_index=0, delta=arguments),
        StreamEvent(type="usage", prompt_tokens=1, completion_tokens=1, total_tokens=2),
        StreamEvent(type="done"),
    ]


def _text_turn(text: str = "ok") -> list[StreamEvent]:
    return [
        StreamEvent(type="text_delta", delta=text),
        StreamEvent(type="usage", prompt_tokens=1, completion_tokens=1, total_tokens=2),
        StreamEvent(type="done"),
    ]


def _harness(turns: List[List[StreamEvent]], **config_kwargs: Any) -> tuple[CoreHarness, EventSink]:
    sink = EventSink()
    harness = CoreHarness(
        registry=ScriptedRegistry(turns),  # type: ignore[arg-type]
        model_id="fake:stamp",
        system_prompt="test",
        config=HarnessConfig(max_turns=4, **config_kwargs),
        tools=[Tool(echo)],
        sink=sink,
    )
    return harness, sink


def _payloads(sink: EventSink, event_type: str) -> list[dict[str, Any]]:
    return [e.payload for e in sink.events if e.event_type == event_type]


def test_duration_helpers() -> None:
    assert duration_ms(100.0, 100.5) == 500
    assert duration_human(500) == "500ms"
    assert duration_human(1500) == "1s"
    assert duration_human(65_000) == "1m 5s"
    assert "started_at" in with_started({})
    ended = with_ended({}, 100.0, ended_mono=100.25)
    assert ended["duration_ms"] == 250
    assert "ended_at" in ended
    assert "duration_human" in ended


def test_control_plane_includes_new_members() -> None:
    values = {member.value for member in ControlPlaneEventType}
    for name in (
        "run_summary",
        "run_phase",
        "assistant_message_started",
        "assistant_message_completed",
        "reasoning_completed",
        "tool_execution_failed",
        "tool_denied",
        "approval_required",
        "approval_resolved",
        "user_input_requested",
        "user_input_received",
        "run_progress",
        "run_metrics",
        "config_changed",
        "jev_decision",
        "child_progress",
    ):
        assert name in values


def test_run_and_turn_and_tool_stamps() -> None:
    harness, sink = _harness(
        [
            _tool_turn("echo", '{"text": "hi"}'),
            _text_turn("done"),
        ]
    )
    result = asyncio.run(harness.run("go"))
    assert "done" in result.output_text

    started = _payloads(sink, "run_started")[0]
    assert isinstance(started.get("started_at"), (int, float))

    for payload in _payloads(sink, "turn_started"):
        assert isinstance(payload.get("started_at"), (int, float))

    for event_type in ("turn_completed", "tool_execution_completed", "run_completed"):
        payloads = _payloads(sink, event_type)
        assert payloads, event_type
        for payload in payloads:
            assert isinstance(payload.get("ended_at"), (int, float)), event_type
            assert isinstance(payload.get("duration_ms"), int), event_type
            assert payload["duration_ms"] >= 0
            assert "duration_human" in payload

    tool_started = _payloads(sink, "tool_execution_started")
    assert tool_started
    assert isinstance(tool_started[0].get("started_at"), (int, float))

    completed = _payloads(sink, "run_completed")[0]
    assert completed["duration_ms"] >= 0
    assert completed["elapsed_seconds"] == pytest.approx(
        completed["duration_ms"] / 1000.0, rel=0.05, abs=0.05
    )

    summaries = _payloads(sink, "run_summary")
    assert summaries, "run_summary required after terminal run"
    assert summaries[0]["status"] == "completed"
    assert isinstance(summaries[0].get("duration_ms"), int)
    assert isinstance(summaries[0].get("ended_at"), (int, float))


def test_cancelled_run_emits_stamped_summary() -> None:
    async def _run() -> EventSink:
        # A tool that blocks so we can cancel mid-run.
        async def slow(text: str = "") -> str:
            await asyncio.sleep(60)
            return text

        sink = EventSink()
        harness = CoreHarness(
            registry=ScriptedRegistry([_tool_turn("slow", "{}")]),  # type: ignore[arg-type]
            model_id="fake:stamp",
            system_prompt="test",
            config=HarnessConfig(max_turns=4),
            tools=[Tool(slow)],
            sink=sink,
        )

        task = asyncio.create_task(harness.run("cancel me"))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(HarnessCancelled):
            await task
        return sink

    sink = asyncio.run(_run())
    cancelled = _payloads(sink, "run_cancelled")
    assert cancelled
    assert isinstance(cancelled[0].get("duration_ms"), int)
    assert isinstance(cancelled[0].get("ended_at"), (int, float))
    summaries = _payloads(sink, "run_summary")
    assert summaries and summaries[0]["status"] == "cancelled"
