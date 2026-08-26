"""Protocol tests for tool results, cancellation, limits, and event identity."""

from __future__ import annotations

import asyncio
import time
from typing import Any, List, Optional

import pytest

from core_ai.types import Message, StreamEvent
from core_harness import (
    ControlCommand,
    CoreHarness,
    EVENT_SCHEMA_VERSION,
    HarnessCancelled,
    HarnessLimitExceeded,
    NullControlPlane,
    NullPersistence,
    Tool,
)
from core_harness.persistence import Checkpoint


IDENTITY_KEYS = ("run_id", "session_id", "seq", "ts", "schema_version")


class RecordingPersistence(NullPersistence):
    def __init__(self) -> None:
        self.checkpoints: list[Checkpoint] = []

    async def save_checkpoint(self, *, checkpoint: Checkpoint) -> None:  # type: ignore[override]
        self.checkpoints.append(checkpoint)


class ScriptedRegistry:
    """Yield a scripted sequence of stream events per model call."""

    def __init__(self, turns: list[list[StreamEvent]]) -> None:
        self.turns = turns
        self.calls = 0

    async def stream(self, model_id: str, messages: list[Message], tools: list[dict[str, Any]]):
        del model_id, messages, tools
        events = self.turns[min(self.calls, len(self.turns) - 1)]
        self.calls += 1
        for event in events:
            yield event


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


def _assert_identity(events: list[Any]) -> None:
    seqs: list[int] = []
    run_ids = set()
    session_ids = set()
    for event in events:
        payload = event.payload
        for key in IDENTITY_KEYS:
            assert key in payload, f"{event.event_type} missing {key}"
        assert payload["schema_version"] == EVENT_SCHEMA_VERSION
        assert isinstance(payload["seq"], int) and payload["seq"] >= 1
        assert isinstance(payload["ts"], (int, float))
        assert payload["run_id"]
        assert payload["session_id"]
        seqs.append(payload["seq"])
        run_ids.add(payload["run_id"])
        session_ids.add(payload["session_id"])
    assert seqs == list(range(1, len(events) + 1))
    assert len(run_ids) == 1
    assert len(session_ids) == 1


def _harness(
    registry: Any,
    *,
    tools: Optional[list[Tool]] = None,
    max_turns: int = 8,
    max_tool_calls: Optional[int] = None,
    max_runtime_seconds: Optional[float] = None,
    max_tokens: Optional[int] = None,
    persistence: Any = None,
    control_plane: Any = None,
) -> tuple[Any, Any, CoreHarness]:
    plane = control_plane or NullControlPlane()
    harness = CoreHarness(
        registry=registry,
        model_id="fake:test-model",
        system_prompt="system",
        tools=tools or [],
        control_plane=plane,
        persistence=persistence,
        max_turns=max_turns,
        max_tool_calls=max_tool_calls,
        max_runtime_seconds=max_runtime_seconds,
        max_tokens=max_tokens,
    )
    return registry, plane, harness


def test_unknown_tool_returns_error_result_instead_of_failing_the_run() -> None:
    registry = ScriptedRegistry([_tool_turn("missing"), _text_turn("recovered")])
    _, plane, harness = _harness(registry)

    result = asyncio.run(harness.run("go"))

    assert result.output_text == "recovered"
    assert result.tool_calls[0].result_status == "error"
    completed = [e for e in plane.events if e.event_type == "tool_execution_completed"]
    assert completed[0].payload["status"] == "error"
    assert "not registered" in completed[0].payload["result"]
    assert plane.events[-1].event_type == "run_completed"
    _assert_identity(plane.events)


def test_invalid_tool_json_returns_error_result() -> None:
    registry = ScriptedRegistry([_tool_turn("echo", "{not-json"), _text_turn("ok")])

    def echo() -> str:
        return "hi"

    _, plane, harness = _harness(registry, tools=[Tool(echo)])
    result = asyncio.run(harness.run("go"))

    assert result.tool_calls[0].result_status == "error"
    completed = [e for e in plane.events if e.event_type == "tool_execution_completed"]
    assert completed[0].payload["status"] == "error"
    assert "Invalid tool arguments" in completed[0].payload["result"]
    assert plane.events[-1].event_type == "run_completed"


def test_tool_exception_returns_error_result() -> None:
    registry = ScriptedRegistry([_tool_turn("boom"), _text_turn("ok")])

    def boom() -> str:
        raise RuntimeError("nope")

    _, plane, harness = _harness(registry, tools=[Tool(boom)])
    result = asyncio.run(harness.run("go"))

    assert result.tool_calls[0].result_status == "error"
    completed = [e for e in plane.events if e.event_type == "tool_execution_completed"]
    assert completed[0].payload["status"] == "error"
    assert "nope" in completed[0].payload["result"]
    assert plane.events[-1].event_type == "run_completed"


def test_every_parallel_tool_call_gets_a_result_on_cancel() -> None:
    events = [
        StreamEvent(type="toolcall_start", content_index=0, tool_call_id="a", tool_name="hold"),
        StreamEvent(type="toolcall_delta", content_index=0, delta="{}"),
        StreamEvent(type="toolcall_start", content_index=1, tool_call_id="b", tool_name="second"),
        StreamEvent(type="toolcall_delta", content_index=1, delta="{}"),
        StreamEvent(type="usage", prompt_tokens=1, completion_tokens=1, total_tokens=2),
        StreamEvent(type="done"),
    ]
    registry = ScriptedRegistry([events])
    plane = NullControlPlane()

    async def hold() -> str:
        await asyncio.sleep(30)
        return "held"

    def second() -> str:
        return "second"

    _, _, harness = _harness(
        registry,
        tools=[Tool(hold), Tool(second)],
        control_plane=plane,
    )

    async def _run() -> None:
        task = asyncio.create_task(harness.run("go"))
        await asyncio.sleep(0.05)
        await plane.send_command(ControlCommand.cancel(reason="stop-tools"))
        await task

    with pytest.raises(HarnessCancelled, match="stop-tools"):
        asyncio.run(_run())

    completed = [e for e in plane.events if e.event_type == "tool_execution_completed"]
    assert len(completed) == 2
    assert {e.payload["status"] for e in completed} <= {"cancelled", "success"}
    assert any(e.payload["status"] == "cancelled" for e in completed)
    assert plane.events[-1].event_type == "run_cancelled"


def test_cancel_stops_active_model_stream_and_persists() -> None:
    class SlowRegistry:
        async def stream(self, model_id, messages, tools):
            yield StreamEvent(type="text_delta", delta="hello")
            await asyncio.sleep(30)
            yield StreamEvent(type="text_delta", delta="world")
            yield StreamEvent(type="done")

    persistence = RecordingPersistence()
    plane = NullControlPlane()
    _, _, harness = _harness(
        SlowRegistry(),
        persistence=persistence,
        control_plane=plane,
    )

    async def _run() -> None:
        task = asyncio.create_task(harness.run("go"))
        await asyncio.sleep(0.05)
        await plane.send_command(ControlCommand.cancel(reason="user_cancel"))
        await asyncio.wait_for(task, timeout=2)

    started = time.monotonic()
    with pytest.raises(HarnessCancelled, match="user_cancel"):
        asyncio.run(_run())
    assert time.monotonic() - started < 2
    assert plane.events[-1].event_type == "run_cancelled"
    assert persistence.checkpoints
    assert persistence.checkpoints[-1].status == "cancelled"
    assert persistence.checkpoints[-1].metadata["reason"] == "user_cancel"
    _assert_identity(plane.events)


def test_max_turns_emits_run_limit_exceeded() -> None:
    registry = ScriptedRegistry([_tool_turn("echo")])

    def echo() -> str:
        return "ok"

    _, plane, harness = _harness(registry, tools=[Tool(echo)], max_turns=1)
    with pytest.raises(HarnessLimitExceeded, match="max_turns"):
        asyncio.run(harness.run("go"))
    assert plane.events[-1].event_type == "run_limit_exceeded"
    assert plane.events[-1].payload["limit"] == "max_turns"
    _assert_identity(plane.events)


def test_max_tool_calls_emits_run_limit_exceeded_and_results_for_all_calls() -> None:
    events = [
        StreamEvent(type="toolcall_start", content_index=0, tool_call_id="a", tool_name="echo"),
        StreamEvent(type="toolcall_delta", content_index=0, delta="{}"),
        StreamEvent(type="toolcall_start", content_index=1, tool_call_id="b", tool_name="echo"),
        StreamEvent(type="toolcall_delta", content_index=1, delta="{}"),
        StreamEvent(type="usage", prompt_tokens=1, completion_tokens=1, total_tokens=2),
        StreamEvent(type="done"),
    ]
    registry = ScriptedRegistry([events])

    def echo() -> str:
        return "ok"

    _, plane, harness = _harness(registry, tools=[Tool(echo)], max_tool_calls=1)
    with pytest.raises(HarnessLimitExceeded, match="max_tool_calls"):
        asyncio.run(harness.run("go"))
    completed = [e for e in plane.events if e.event_type == "tool_execution_completed"]
    assert len(completed) == 2
    assert completed[0].payload["status"] == "success"
    assert completed[1].payload["status"] == "error"
    assert plane.events[-1].event_type == "run_limit_exceeded"
    assert plane.events[-1].payload["limit"] == "max_tool_calls"


def test_max_tokens_emits_run_limit_exceeded() -> None:
    registry = ScriptedRegistry([_text_turn("hi")])
    _, plane, harness = _harness(registry, max_tokens=1)
    with pytest.raises(HarnessLimitExceeded, match="max_tokens"):
        asyncio.run(harness.run("go"))
    assert plane.events[-1].event_type == "run_limit_exceeded"
    assert plane.events[-1].payload["limit"] == "max_tokens"


def test_model_retry_event_keeps_run_alive() -> None:
    events = [
        StreamEvent(type="retry", retry_after=2.5, retry_attempt=1),
        *_text_turn("recovered"),
    ]
    registry = ScriptedRegistry([events])
    _, plane, harness = _harness(registry)

    result = asyncio.run(harness.run("go"))

    assert result.output_text == "recovered"
    retry = next(
        event for event in plane.events if event.event_type == "model_retry_scheduled"
    )
    assert retry.payload["retry_after"] == 2.5
    assert retry.payload["attempt"] == 1
    assert retry.payload["reason"] == "rate_limit"
    assert plane.events[-1].event_type == "run_completed"


def test_max_runtime_stops_stream() -> None:
    class SlowRegistry:
        async def stream(self, model_id, messages, tools):
            yield StreamEvent(type="text_delta", delta="hello")
            await asyncio.sleep(30)
            yield StreamEvent(type="done")

    _, plane, harness = _harness(SlowRegistry(), max_runtime_seconds=0.1)
    started = time.monotonic()
    with pytest.raises(HarnessLimitExceeded, match="max_runtime"):
        asyncio.run(harness.run("go"))
    assert time.monotonic() - started < 3
    assert plane.events[-1].event_type == "run_limit_exceeded"
    assert plane.events[-1].payload["limit"] == "max_runtime_seconds"


def test_tool_timeout_status_when_runtime_expires_during_execution() -> None:
    registry = ScriptedRegistry([_tool_turn("hold"), _text_turn("ok")])

    async def hold() -> str:
        await asyncio.sleep(30)
        return "held"

    _, plane, harness = _harness(
        registry,
        tools=[Tool(hold)],
        max_runtime_seconds=0.15,
    )
    with pytest.raises(HarnessLimitExceeded, match="max_runtime"):
        asyncio.run(harness.run("go"))
    completed = [e for e in plane.events if e.event_type == "tool_execution_completed"]
    assert completed
    assert completed[0].payload["status"] in {"timeout", "cancelled", "error"}
    assert plane.events[-1].event_type == "run_limit_exceeded"
