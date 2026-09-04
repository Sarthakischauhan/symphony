"""Unit tests for live-tool cap policy (no full TUI App)."""

from __future__ import annotations

from coding_agent.tui.tools.calls import (
    ToolCallSnapshot,
    ToolCallSummary,
    ToolCallWidget,
    make_tool_widget,
)
from coding_agent.tui.transcript.live_tools import reconcile_live_tools
from coding_agent.tui.transcript.process import ReasoningWidget


def _done_tool(call_id: str, name: str = "read_file") -> ToolCallWidget:
    widget = ToolCallWidget(call_id, name)
    widget.status = "done"
    return widget


def _running_tool(call_id: str, name: str = "bash") -> ToolCallWidget:
    widget = ToolCallWidget(call_id, name)
    widget.status = "running"
    return widget


def _call_ids(items: list[object]) -> list[str]:
    return [item.call_id for item in items if isinstance(item, ToolCallWidget)]


def _summaries(items: list[object]) -> list[ToolCallSummary]:
    return [item for item in items if isinstance(item, ToolCallSummary)]


def test_reconcile_keeps_newest_completed_live_and_folds_older_into_one_explored() -> None:
    """Limit N with N+K completed: newest N live, older K in one Explored above them."""
    limit, extra = 8, 4
    tools: dict[str, object] = {}
    timeline: list[object] = []
    for index in range(limit + extra):
        widget = _done_tool(f"read-{index}")
        tools[widget.call_id] = widget
        timeline.append(widget)

    reconcile_live_tools(timeline, tools, limit=limit)

    summaries = _summaries(timeline)
    live = [item for item in timeline if isinstance(item, ToolCallWidget)]
    assert len(live) == limit
    assert _call_ids(live) == [f"read-{index}" for index in range(extra, limit + extra)]
    assert len(summaries) == 1
    assert summaries[0].count == extra
    assert summaries[0].call_ids == [f"read-{index}" for index in range(extra)]
    assert timeline.index(summaries[0]) < min(timeline.index(item) for item in live)
    assert all(tools[call_id] is summaries[0] for call_id in summaries[0].call_ids)


def test_reconcile_is_per_run_and_ignores_reasoning_boundaries() -> None:
    """Reasoning no longer splits stretches: the cap applies to the whole run."""
    tools: dict[str, object] = {}
    timeline: list[object] = []
    for index in range(5):
        widget = _done_tool(f"a-{index}")
        tools[widget.call_id] = widget
        timeline.append(widget)
    reasoning = ReasoningWidget("Considering the next batch.")
    timeline.append(reasoning)
    for index in range(5):
        widget = _done_tool(f"b-{index}")
        tools[widget.call_id] = widget
        timeline.append(widget)

    reconcile_live_tools(timeline, tools, limit=3)

    summaries = _summaries(timeline)
    assert len(summaries) == 1
    assert summaries[0].call_ids == ["a-0", "a-1", "a-2", "a-3", "a-4", "b-0", "b-1"]
    assert _call_ids(timeline) == ["b-2", "b-3", "b-4"]
    assert timeline.index(summaries[0]) < timeline.index(reasoning)
    assert reasoning in timeline


def test_reconcile_leaves_everything_live_under_the_limit() -> None:
    thinking = object()
    tools: dict[str, object] = {}
    timeline: list[object] = [thinking]
    for index in range(5):
        widget = _done_tool(f"a-{index}")
        tools[widget.call_id] = widget
        timeline.append(widget)
    timeline.append(ReasoningWidget("Considering the next batch."))
    for index in range(3):
        widget = _done_tool(f"b-{index}")
        tools[widget.call_id] = widget
        timeline.append(widget)

    reconcile_live_tools(timeline, tools)

    assert _summaries(timeline) == []
    assert _call_ids(timeline) == [f"a-{index}" for index in range(5)] + [
        f"b-{index}" for index in range(3)
    ]
    assert timeline[0] is thinking


def test_reconcile_in_progress_tools_stay_live_and_do_not_count() -> None:
    """Running cards never fold and never push completed cards out of the live set."""
    running = [_running_tool(f"run-{index}") for index in range(3)]
    done = [_done_tool(f"read-{index}") for index in range(2)]
    timeline: list[object] = [*running, *done]
    tools = {item.call_id: item for item in timeline if isinstance(item, ToolCallWidget)}

    reconcile_live_tools(timeline, tools, limit=2)

    assert _summaries(timeline) == []
    assert _call_ids(timeline) == ["run-0", "run-1", "run-2", "read-0", "read-1"]


def test_reconcile_does_not_collapse_spawn_or_running_tools() -> None:
    spawn = _done_tool("spawn-1", "spawn_agent")
    running = _running_tool("run-1")
    done = [_done_tool(f"read-{index}") for index in range(4)]
    timeline: list[object] = [spawn, running, *done]
    tools = {item.call_id: item for item in timeline if isinstance(item, ToolCallWidget)}

    reconcile_live_tools(timeline, tools, limit=2)

    assert spawn in timeline
    assert running in timeline
    summaries = _summaries(timeline)
    assert len(summaries) == 1
    assert summaries[0].call_ids == ["read-0", "read-1"]
    assert _call_ids(timeline) == ["spawn-1", "run-1", "read-2", "read-3"]


def test_reconcile_late_finisher_joins_existing_explored() -> None:
    """An older card that completes later folds into the same Explored row."""
    late = _running_tool("late")
    done = [_done_tool(f"read-{index}") for index in range(3)]
    timeline: list[object] = [late, *done]
    tools = {item.call_id: item for item in timeline if isinstance(item, ToolCallWidget)}

    reconcile_live_tools(timeline, tools, limit=2)
    assert _call_ids(timeline) == ["late", "read-1", "read-2"]
    assert [summary.call_ids for summary in _summaries(timeline)] == [["read-0"]]

    late.status = "done"
    reconcile_live_tools(timeline, tools, limit=2)

    summaries = _summaries(timeline)
    assert len(summaries) == 1
    assert summaries[0].call_ids == ["read-0", "late"]
    assert _call_ids(timeline) == ["read-1", "read-2"]
    assert tools["late"] is summaries[0]
    assert timeline.index(summaries[0]) < timeline.index(done[1])


def test_reconcile_folds_incrementally_as_tools_complete() -> None:
    """Bottom-up: as each new card completes, the oldest live card folds."""
    timeline: list[object] = []
    tools: dict[str, object] = {}
    for index in range(6):
        widget = _done_tool(f"read-{index}")
        tools[widget.call_id] = widget
        timeline.append(widget)
        reconcile_live_tools(timeline, tools, limit=3)
        expected_live = [f"read-{i}" for i in range(max(0, index - 2), index + 1)]
        assert _call_ids(timeline) == expected_live

    summaries = _summaries(timeline)
    assert len(summaries) == 1
    assert summaries[0].call_ids == ["read-0", "read-1", "read-2"]
    assert timeline.index(summaries[0]) == 0


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


def test_tool_call_summary_keeps_snapshots_of_folded_tools() -> None:
    widget = make_tool_widget("read-1", "read_file")
    widget.set_arguments({"path": "src/app.py"})
    widget.set_result("line one\nline two")
    summary = ToolCallSummary()

    summary.add_call(widget)
    summary.add_call(widget)

    assert summary.count == 1
    snapshot = summary.calls[0]
    assert isinstance(snapshot, ToolCallSnapshot)
    assert snapshot.call_id == "read-1"
    assert snapshot.label == "Read"
    assert snapshot.detail == "src/app.py"
    assert snapshot.status == "done"
    assert summary.snapshot_text() == "✓  Read  src/app.py\n   Read 2 lines (17 bytes)"
