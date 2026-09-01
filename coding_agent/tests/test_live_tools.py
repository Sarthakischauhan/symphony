"""Unit tests for live-tool cap policy (no full TUI App)."""

from __future__ import annotations

from coding_agent.tui.tools.calls import ToolCallSummary, ToolCallWidget
from coding_agent.tui.transcript.live_tools import reconcile_live_tools
from coding_agent.tui.transcript.process import ReasoningWidget


def _done_tool(call_id: str, name: str = "read_file") -> ToolCallWidget:
    widget = ToolCallWidget(call_id, name)
    widget.status = "done"
    return widget


def test_reconcile_folds_overflow_into_one_explored_summary() -> None:
    tools: dict[str, object] = {}
    timeline: list[object] = []
    for index in range(12):
        widget = _done_tool(f"read-{index}")
        tools[widget.call_id] = widget
        timeline.append(widget)

    reconcile_live_tools(timeline, tools, limit=8)

    summaries = [item for item in timeline if isinstance(item, ToolCallSummary)]
    live = [item for item in timeline if isinstance(item, ToolCallWidget)]
    assert len(live) == 8
    assert [item.call_id for item in live] == [f"read-{index}" for index in range(4, 12)]
    assert len(summaries) == 1
    assert summaries[0].count == 4
    assert summaries[0].call_ids == ["read-0", "read-1", "read-2", "read-3"]
    assert all(tools[call_id] is summaries[0] for call_id in summaries[0].call_ids)


def test_reconcile_starts_new_explored_line_after_reasoning() -> None:
    tools: dict[str, object] = {}
    timeline: list[object] = []
    for index in range(5):
        widget = _done_tool(f"a-{index}")
        tools[widget.call_id] = widget
        timeline.append(widget)
    timeline.append(ReasoningWidget("Considering the next batch."))
    for index in range(5):
        widget = _done_tool(f"b-{index}")
        tools[widget.call_id] = widget
        timeline.append(widget)

    reconcile_live_tools(timeline, tools, limit=3)

    summaries = [item for item in timeline if isinstance(item, ToolCallSummary)]
    live = [item for item in timeline if isinstance(item, ToolCallWidget)]
    assert len(summaries) == 2
    assert summaries[0].count == 5
    assert summaries[1].count == 2
    assert len(live) == 3
    assert [item.call_id for item in live] == ["b-2", "b-3", "b-4"]
    assert isinstance(timeline[1], ReasoningWidget)


def test_reconcile_does_not_collapse_spawn_or_running_tools() -> None:
    spawn = _done_tool("spawn-1", "spawn_agent")
    running = ToolCallWidget("run-1", "bash")
    running.status = "running"
    done = [_done_tool(f"read-{index}") for index in range(4)]
    timeline: list[object] = [spawn, running, *done]
    tools = {item.call_id: item for item in timeline if isinstance(item, ToolCallWidget)}

    reconcile_live_tools(timeline, tools, limit=2)

    assert spawn in timeline
    assert running in timeline
    live_reads = [
        item
        for item in timeline
        if isinstance(item, ToolCallWidget) and item.tool_name == "read_file"
    ]
    summaries = [item for item in timeline if isinstance(item, ToolCallSummary)]
    assert len(live_reads) == 2
    assert len(summaries) == 1
    assert summaries[0].count == 2
