"""Unit tests for live-tool cap policy (no full TUI App)."""

from __future__ import annotations

from coding_agent.tui.tools.calls import ToolCallSummary, ToolCallWidget
from coding_agent.tui.transcript.live_tools import reconcile_live_tools
from coding_agent.tui.transcript.process import ReasoningWidget


def _done_tool(call_id: str, name: str = "read_file") -> ToolCallWidget:
    widget = ToolCallWidget(call_id, name)
    widget.status = "done"
    return widget


def _call_ids(items: list[object]) -> list[str]:
    return [item.call_id for item in items if isinstance(item, ToolCallWidget)]


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
    assert summaries[0].count == 2
    assert summaries[1].count == 2
    assert summaries[0].call_ids == ["a-0", "a-1"]
    assert summaries[1].call_ids == ["b-0", "b-1"]
    assert _call_ids(live) == ["a-2", "a-3", "a-4", "b-2", "b-3", "b-4"]
    assert any(isinstance(item, ReasoningWidget) for item in timeline)


def test_reconcile_does_not_collapse_second_stretch_under_limit() -> None:
    """Two batches of 5 done tools split by reasoning stay fully live at the default cap.

    ``ThinkingStatus`` is first in ``timeline_items()`` and must not split stretches.
    A non-widget sentinel stands in here so this test stays App-free.
    """
    thinking = object()
    tools: dict[str, object] = {}
    timeline: list[object] = [thinking]
    for index in range(5):
        widget = _done_tool(f"a-{index}")
        tools[widget.call_id] = widget
        timeline.append(widget)
    timeline.append(ReasoningWidget("Considering the next batch."))
    for index in range(5):
        widget = _done_tool(f"b-{index}")
        tools[widget.call_id] = widget
        timeline.append(widget)

    reconcile_live_tools(timeline, tools)

    summaries = [item for item in timeline if isinstance(item, ToolCallSummary)]
    live = [item for item in timeline if isinstance(item, ToolCallWidget)]
    assert summaries == []
    assert len(live) == 10
    assert _call_ids(live) == [f"a-{index}" for index in range(5)] + [
        f"b-{index}" for index in range(5)
    ]
    assert timeline[0] is thinking
    assert any(isinstance(item, ReasoningWidget) for item in timeline)


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


def test_tool_call_summary_line_uses_amber_explored_and_muted_count() -> None:
    summary = ToolCallSummary()
    summary.add_call("read-0")
    summary.add_call("read-1")
    line = summary._line()
    assert line.plain == "[ Explored       2 tools]"
    styles = {
        line.plain[span.start : span.end]: str(span.style) for span in line.spans
    }
    assert styles["Explored"] == "#d7a84b"
    assert styles["       2 tools]"] == "#666666"
