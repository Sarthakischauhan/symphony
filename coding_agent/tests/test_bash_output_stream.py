"""The bash tool streams live output to the sink as tool_execution_output."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from core_harness import EventSink
from core_harness.tools import current_tool_call_id

from coding_agent import CodingAgent
from coding_agent.config import CodingAgentConfig, LangfuseConfig, LearningConfig
from coding_agent.tools import BashTool
from coding_agent.tools.bash import OUTPUT_EVENT, OUTPUT_EVENT_CHARS
from scripted_registry import ScriptedRegistry

LINES_COMMAND = "for i in 1 2 3 4 5 6; do echo line $i; sleep 0.12; done; echo oops >&2"


async def _execute(tool: BashTool, sink: EventSink | None, call_id: str, **args: object) -> str:
    token = current_tool_call_id.set(call_id)
    try:
        return await tool.execute(sink=sink, args=dict(args))
    finally:
        current_tool_call_id.reset(token)


def _deltas(sink: EventSink) -> list[str]:
    return [event.payload["delta"] for event in sink.events if event.event_type == OUTPUT_EVENT]


def test_multi_line_output_streams_in_order_and_result_is_unchanged(tmp_path: Path) -> None:
    tool = BashTool(tmp_path)
    sink = EventSink()

    async def _run() -> tuple[str, str]:
        streamed = await _execute(tool, sink, "call-1", command=LINES_COMMAND)
        plain = await _execute(tool, None, "call-2", command=LINES_COMMAND)
        return streamed, plain

    streamed, plain = asyncio.run(_run())
    deltas = _deltas(sink)
    # Coalesced, but live: a 0.7 s command produces several chunks, not one.
    assert 3 <= len(deltas) <= 12
    assert "".join(deltas) == "".join(f"line {i}\n" for i in range(1, 7)) + "oops\n"
    assert all(event.payload["tool_call_id"] == "call-1" for event in sink.events)
    assert all(event.payload["tool_name"] == "bash" for event in sink.events)
    assert streamed == plain == "\n".join(f"line {i}" for i in range(1, 7)) + "\noops"


def test_nothing_is_emitted_without_a_sink_or_tool_call(tmp_path: Path) -> None:
    tool = BashTool(tmp_path)
    sink = EventSink()

    async def _run() -> tuple[str, str]:
        no_sink = await _execute(tool, None, "call-1", command="echo hi")
        no_call = await _execute(tool, sink, "", command="echo hi")
        return no_sink, no_call

    assert asyncio.run(_run()) == ("hi", "hi")
    assert sink.events == []


def test_timeout_streams_output_before_the_kill(tmp_path: Path) -> None:
    tool = BashTool(tmp_path)
    sink = EventSink()
    command = "echo before-sleep; sleep 30"

    started = time.monotonic()
    result = asyncio.run(_execute(tool, sink, "call-1", command=command, timeout=1))
    assert time.monotonic() - started < 5
    assert result == "timed out after 1s\nbefore-sleep"
    assert "".join(_deltas(sink)) == "before-sleep\n"


def test_cancel_stops_streaming_and_kills_the_command(tmp_path: Path) -> None:
    tool = BashTool(tmp_path)
    sink = EventSink()

    async def _run() -> None:
        task = asyncio.create_task(
            _execute(tool, sink, "call-1", command="while true; do echo tick; sleep 0.05; done", timeout=30)
        )
        await asyncio.sleep(0.4)
        task.cancel()
        started = time.monotonic()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert time.monotonic() - started < 2
        emitted = len(sink.events)
        assert emitted >= 1
        await asyncio.sleep(0.3)
        assert len(sink.events) == emitted

    asyncio.run(_run())


def test_a_burst_sends_only_its_newest_lines(tmp_path: Path) -> None:
    tool = BashTool(tmp_path)
    sink = EventSink()
    command = "python3 -c \"[print(f'row {i:05d}') for i in range(20000)]\""

    streamed = asyncio.run(_execute(tool, sink, "call-1", command=command))
    plain = asyncio.run(_execute(tool, None, "call-2", command=command))
    deltas = _deltas(sink)
    assert all(len(delta) <= OUTPUT_EVENT_CHARS + 1 for delta in deltas)
    assert deltas[-1].endswith("row 19999\n")
    # Every chunk is whole lines, so the live tail never shows a torn row.
    assert all(line.startswith("row ") for delta in deltas for line in delta.splitlines())
    assert streamed == plain
    assert "truncated" in streamed


def test_harness_run_emits_output_between_start_and_completion(tmp_path: Path) -> None:
    command = "for i in 1 2 3; do echo step $i; sleep 0.15; done"
    registry = ScriptedRegistry({"run it": [[("bash", {"command": command})]]})
    sink = EventSink()
    agent = CodingAgent(
        registry=registry,
        model_id="fake:test-model",
        workspace=tmp_path,  # type: ignore[arg-type]
        sink=sink,
        config=CodingAgentConfig(
            learning=LearningConfig(enabled=False), langfuse=LangfuseConfig(enabled=False), unattended=True
        ),
    )
    result = asyncio.run(agent.run("run it"))
    assert result.output_text == "all done"

    types = [event.event_type for event in sink.events]
    started = types.index("tool_execution_started")
    completed = types.index("tool_execution_completed")
    outputs = [index for index, kind in enumerate(types) if kind == OUTPUT_EVENT]
    assert outputs and started < outputs[0] and outputs[-1] < completed
    call_id = sink.events[started].payload["tool_call_id"]
    assert {sink.events[index].payload["tool_call_id"] for index in outputs} == {call_id}
    assert "".join(sink.events[index].payload["delta"] for index in outputs) == "step 1\nstep 2\nstep 3\n"
    assert sink.events[completed].payload["result"] == "step 1\nstep 2\nstep 3"
