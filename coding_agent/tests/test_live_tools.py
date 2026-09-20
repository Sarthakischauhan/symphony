"""Unit tests for stretch-based live-tool folding (no full TUI App)."""

from __future__ import annotations

from coding_agent.tui.motion import enter_row, settle_row
from coding_agent.tui.tools.activity import (
    COMPLETION_VERBS,
    format_explored_duration,
    same_activity_group,
)
from coding_agent.tui.tools.calls import (
    ToolCallWidget,
    make_tool_widget,
)
from coding_agent.tui.tools.snapshots import (
    CompletedRunSummary,
    ToolCallSnapshot,
    ToolCallSummary,
    snapshot_from_call,
)
from coding_agent.tui.transcript.live_tools import (
    collectable_tools,
    is_collectable_thought,
    is_collectable_tool,
    is_hot_tool,
    is_interactive_tool,
    is_tool_stretch_item,
    reconcile_live_tools,
    release_live_binding,
    segment_tool_stretches,
)
from coding_agent.tui.transcript.messages import AssistantMessage
from coding_agent.tui.transcript.process import ReasoningWidget


def _done_tool(call_id: str, name: str = "read_file") -> ToolCallWidget:
    widget = ToolCallWidget(call_id, name)
    widget.status = "done"
    return widget


def _running_tool(call_id: str, name: str = "bash") -> ToolCallWidget:
    widget = ToolCallWidget(call_id, name)
    widget.status = "running"
    return widget


def _text(content: str) -> AssistantMessage:
    return AssistantMessage(content, enter=False)


def _call_ids(items: list[object]) -> list[str]:
    return [item.call_id for item in items if isinstance(item, ToolCallWidget)]


def _summaries(items: list[object]) -> list[ToolCallSummary]:
    return [item for item in items if isinstance(item, ToolCallSummary)]


def test_hot_vs_collectable_policy_helpers() -> None:
    running = _running_tool("run")
    done = _done_tool("read")
    image = _done_tool("img", "generate_image")
    spawn = _done_tool("child", "spawn_agent")
    spawn.keep_in_transcript = True
    thought = ReasoningWidget("## Inspecting\n\nBody")
    thought.complete()
    live_thought = ReasoningWidget("Still thinking")
    summary = ToolCallSummary()
    summary.add_call("read-0")

    assert is_hot_tool(running)
    assert not is_hot_tool(done)
    assert is_collectable_tool(done)
    assert not is_collectable_tool(running)
    assert not is_collectable_tool(image)
    assert is_collectable_tool(image, include_interactive=True)
    assert is_interactive_tool(image)
    assert is_interactive_tool(spawn)
    assert not is_collectable_tool(spawn)
    assert is_collectable_thought(thought)
    assert not is_collectable_thought(live_thought)
    assert collectable_tools([running, done, image]) == [done]
    assert is_tool_stretch_item(done)
    assert is_tool_stretch_item(summary)
    assert not is_tool_stretch_item(_text("plain"))


def test_release_live_binding_points_at_collected_form() -> None:
    widget = _done_tool("read")
    summary = ToolCallSummary()
    tools = {widget.call_id: widget}

    release_live_binding(tools, widget, summary)

    assert tools["read"] is summary
    assert not isinstance(tools["read"], ToolCallWidget)


def test_segment_tool_stretches_splits_on_non_tool_widgets() -> None:
    first = [_done_tool(f"a-{index}") for index in range(3)]
    text = _text("The emoji width is the culprit.")
    second = [_done_tool(f"b-{index}") for index in range(5)]
    stretches = segment_tool_stretches([*first, text, *second])

    assert [([item.call_id for item in stretch], interrupted) for stretch, interrupted in stretches] == [
        (["a-0", "a-1", "a-2"], True),
        (["b-0", "b-1", "b-2", "b-3", "b-4"], False),
    ]


def test_completed_tools_stay_live_until_interrupted() -> None:
    tools: dict[str, object] = {}
    timeline: list[object] = []
    for index in range(3):
        widget = _done_tool(f"read-{index}")
        tools[widget.call_id] = widget
        timeline.append(widget)

    reconcile_live_tools(timeline, tools)

    assert _call_ids(timeline) == ["read-0", "read-1", "read-2"]
    assert _summaries(timeline) == []
    assert all(tools[call_id] is widget for call_id, widget in zip(
        ["read-0", "read-1", "read-2"], timeline, strict=True
    ))


def test_tools_then_text_then_tools_makes_two_folds() -> None:
    tools: dict[str, object] = {}
    first = [_done_tool(f"a-{index}") for index in range(3)]
    second = [_done_tool(f"b-{index}") for index in range(5)]
    for widget in [*first, *second]:
        tools[widget.call_id] = widget
    mid = _text("The emoji width is the culprit.")
    timeline: list[object] = [*first, mid, *second]

    reconcile_live_tools(timeline, tools)

    summaries = _summaries(timeline)
    assert len(summaries) == 1
    assert summaries[0].call_ids == ["a-0", "a-1", "a-2"]
    assert _call_ids(timeline) == ["b-0", "b-1", "b-2", "b-3", "b-4"]
    assert mid in timeline

    timeline.append(_text("Spacing is now correct."))
    reconcile_live_tools(timeline, tools)

    summaries = _summaries(timeline)
    assert [summary.call_ids for summary in summaries] == [
        ["a-0", "a-1", "a-2"],
        ["b-0", "b-1", "b-2", "b-3", "b-4"],
    ]
    assert _call_ids(timeline) == []


def test_reasoning_splits_tool_stretches() -> None:
    tools: dict[str, object] = {}
    timeline: list[object] = []
    for index in range(3):
        widget = _done_tool(f"a-{index}")
        tools[widget.call_id] = widget
        timeline.append(widget)
    reasoning = ReasoningWidget("Considering the next batch.")
    timeline.append(reasoning)
    for index in range(5):
        widget = _done_tool(f"b-{index}")
        tools[widget.call_id] = widget
        timeline.append(widget)

    reconcile_live_tools(timeline, tools)

    summaries = _summaries(timeline)
    assert [summary.call_ids for summary in summaries] == [["a-0", "a-1", "a-2"]]
    assert _call_ids(timeline) == ["b-0", "b-1", "b-2", "b-3", "b-4"]
    assert reasoning in timeline
    assert all("thought" not in summary.title for summary in summaries)


def test_lone_completed_thought_stays_as_thought() -> None:
    thought = ReasoningWidget("## Inspecting files\n\nReasoning body")
    thought.complete()
    text = _text("Finished the requested changes.")
    timeline: list[object] = [thought, text]

    reconcile_live_tools(timeline)

    assert thought in timeline
    assert _summaries(timeline) == []
    assert thought.title.startswith("[ Thought for ")
    assert thought.title.endswith("s ]")


def test_multiple_completed_thoughts_fold_into_explored() -> None:
    first = ReasoningWidget("## Inspecting files\n\nFirst")
    first.complete()
    second = ReasoningWidget("## Planning changes\n\nSecond")
    second.complete()
    text = _text("Finished the requested changes.")
    timeline: list[object] = [first, second, text]

    reconcile_live_tools(timeline)

    summaries = _summaries(timeline)
    assert first not in timeline
    assert second not in timeline
    assert len(summaries) == 1
    assert summaries[0]._thought_count() == 2


def test_uninterrupted_stretch_is_not_capped_by_ten() -> None:
    tools: dict[str, object] = {}
    timeline: list[object] = []
    for index in range(12):
        widget = _done_tool(f"read-{index}")
        tools[widget.call_id] = widget
        timeline.append(widget)

    reconcile_live_tools(timeline, tools, limit=8)

    assert _call_ids(timeline) == [f"read-{index}" for index in range(12)]
    assert _summaries(timeline) == []

    reconcile_live_tools(timeline, tools, final=True)

    summaries = _summaries(timeline)
    assert len(summaries) == 1
    assert summaries[0].count == 12
    assert summaries[0].call_ids == [f"read-{index}" for index in range(12)]


def test_reconcile_in_progress_tools_stay_live_and_do_not_count() -> None:
    running = [_running_tool(f"run-{index}") for index in range(3)]
    done = [_done_tool(f"read-{index}") for index in range(2)]
    text = _text("Checking the topbar layout.")
    timeline: list[object] = [*running, *done, text]
    tools = {item.call_id: item for item in timeline if isinstance(item, ToolCallWidget)}

    reconcile_live_tools(timeline, tools)

    assert [summary.call_ids for summary in _summaries(timeline)] == [["read-0", "read-1"]]
    assert _call_ids(timeline) == ["run-0", "run-1", "run-2"]
    assert all(is_hot_tool(item) for item in timeline if isinstance(item, ToolCallWidget))


def test_reconcile_does_not_collapse_spawn_or_running_tools() -> None:
    spawn = _done_tool("spawn-1", "spawn_agent")
    spawn.keep_in_transcript = True
    running = _running_tool("run-1")
    done = [_done_tool(f"read-{index}") for index in range(4)]
    text = _text("Inspecting the CSS for spacing issues.")
    timeline: list[object] = [spawn, running, *done, text]
    tools = {item.call_id: item for item in timeline if isinstance(item, ToolCallWidget)}

    reconcile_live_tools(timeline, tools)

    assert spawn in timeline
    assert running in timeline
    summaries = _summaries(timeline)
    assert [summary.call_ids for summary in summaries] == [
        ["read-0", "read-1", "read-2", "read-3"],
    ]
    assert _call_ids(timeline) == ["spawn-1", "run-1"]


def test_reconcile_late_finisher_joins_existing_explored() -> None:
    """A late completion in the same interrupted stretch joins that Explored row."""
    late = _running_tool("late")
    done = [_done_tool(f"read-{index}") for index in range(3)]
    text = _text("Applying the fix.")
    timeline: list[object] = [late, *done, text]
    tools = {item.call_id: item for item in timeline if isinstance(item, ToolCallWidget)}

    reconcile_live_tools(timeline, tools)
    assert _call_ids(timeline) == ["late"]
    assert [summary.call_ids for summary in _summaries(timeline)] == [
        ["read-0", "read-1", "read-2"],
    ]

    late.status = "done"
    reconcile_live_tools(timeline, tools)

    summaries = _summaries(timeline)
    assert len(summaries) == 1
    assert summaries[0].call_ids == ["read-0", "read-1", "read-2", "late"]
    assert tools["late"] is summaries[0]
    assert _call_ids(timeline) == []


def test_text_after_a_stretch_starts_a_new_fold() -> None:
    timeline: list[object] = []
    tools: dict[str, object] = {}
    for index in range(3):
        widget = _done_tool(f"read-{index}")
        tools[widget.call_id] = widget
        timeline.append(widget)
        reconcile_live_tools(timeline, tools)
    assert _summaries(timeline) == []

    timeline.append(_text("The emoji width is the culprit."))
    reconcile_live_tools(timeline, tools)
    assert [summary.call_ids for summary in _summaries(timeline)] == [
        ["read-0", "read-1", "read-2"],
    ]

    for index in range(3, 6):
        widget = _done_tool(f"read-{index}")
        tools[widget.call_id] = widget
        timeline.append(widget)
        reconcile_live_tools(timeline, tools)
    assert _call_ids(timeline) == ["read-3", "read-4", "read-5"]

    timeline.append(_text("Spacing is now correct."))
    reconcile_live_tools(timeline, tools)
    assert [summary.call_ids for summary in _summaries(timeline)] == [
        ["read-0", "read-1", "read-2"],
        ["read-3", "read-4", "read-5"],
    ]


def test_completed_cards_do_not_expand_the_live_tree_unbounded() -> None:
    tools: dict[str, object] = {}
    timeline: list[object] = [_running_tool("hot")]
    tools["hot"] = timeline[0]
    for index in range(25):
        widget = _done_tool(f"read-{index}")
        tools[widget.call_id] = widget
        timeline.append(widget)
    timeline.append(_text("Done inspecting."))
    reconcile_live_tools(timeline, tools)

    live = [item for item in timeline if isinstance(item, ToolCallWidget)]
    assert _call_ids(live) == ["hot"]
    assert sum(summary.count for summary in _summaries(timeline)) == 25
    assert all(
        isinstance(tools[call_id], ToolCallSummary)
        for call_id in tools
        if call_id != "hot"
    )


def test_tool_call_summary_line_uses_subtle_explored_and_muted_count() -> None:
    summary = ToolCallSummary()
    summary.add_call("read-0")
    summary.add_call("read-1")
    assert summary.title == "Explored · 2 tools"
    assert summary.render().plain == "[ Explored · 2 tools ]"


def test_tool_call_summary_discloses_non_interactive_snapshots() -> None:
    widget = make_tool_widget("read-1", "read_file")
    widget.set_arguments({"path": "src/app.py"})
    widget.set_result("line one\nline two")
    summary = ToolCallSummary()
    summary.add_call(widget)

    assert "src/app.py" not in summary.render().plain
    summary.toggle()

    rendered = summary.render().plain
    assert rendered.startswith("[ Explored · 1 tool ]")
    assert "  Read  src/app.py" in rendered
    assert "Read 2 lines (17 bytes)" not in rendered


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


def test_finalization_folds_partial_batch_and_completed_subagents() -> None:
    done = _done_tool("read")
    spawn = _done_tool("child", "spawn_agent")
    spawn.keep_in_transcript = True
    running = _running_tool("running")
    timeline = [done, spawn, running]
    tools = {item.call_id: item for item in timeline}

    reconcile_live_tools(timeline, tools, final=True)
    reconcile_live_tools(timeline, tools, final=True)

    assert _call_ids(timeline) == ["running"]
    assert len(_summaries(timeline)) == 1
    assert set(_summaries(timeline)[0].call_ids) == {"read", "child"}
    assert tools["read"] is tools["child"]


def test_summary_keeps_failures_visible_when_collapsed() -> None:
    summary = ToolCallSummary()
    summary.add_call(ToolCallSnapshot("failed", status="failed", result="Permission denied"))

    assert "1 failed" in summary.render().plain
    assert summary.has_class("has-failures")
    summary.toggle()
    assert "Permission denied" not in summary.render().plain


def test_finalization_closes_expanded_batches_without_new_tools() -> None:
    summary = ToolCallSummary()
    summary.add_call("read")
    summary.toggle()
    reconcile_live_tools([summary], final=True)
    assert not summary.is_expanded


def test_interrupted_completed_thought_is_compacted_but_live_thought_remains() -> None:
    thought = ReasoningWidget("## Inspecting files\n\nPrivate reasoning body")
    thought.complete()
    tool = _done_tool("read")
    live_thought = ReasoningWidget("Still thinking")
    timeline = [tool, thought, live_thought]

    reconcile_live_tools(timeline)

    assert thought in timeline
    assert live_thought in timeline
    summaries = _summaries(timeline)
    assert len(summaries) == 1
    assert summaries[0].title == "Explored · 1 tool"
    assert summaries[0].call_ids == ["read"]
    assert thought.title.startswith("[ Thought for ")
    assert thought.title.endswith("s ]")


def test_finalization_keeps_a_lone_thought() -> None:
    thought = ReasoningWidget("## Answering\n\nDetails")
    thought.complete()
    timeline = [thought]

    reconcile_live_tools(timeline, final=True)

    assert thought in timeline
    assert _summaries(timeline) == []
    assert thought.title.startswith("[ Thought for ")
    assert thought.title.endswith("s ]")


def test_assistant_message_is_plain_text_without_agent_chrome() -> None:
    streaming = AssistantMessage("Inspecting the CSS for spacing issues.", streaming=True)
    finished = AssistantMessage("Spacing is now correct.")

    for message in (streaming, finished):
        rendered = str(message.render())
        assert "SYMPHONY" not in rendered
        assert "◆" not in rendered
        assert message.archive_text() == message.message_text
        assert "SYMPHONY" not in message.archive_text()
        assert "◆" not in message.archive_text()
    assert streaming.message_text == "Inspecting the CSS for spacing issues."
    assert finished.message_text == "Spacing is now correct."


def test_activity_groups_form_separate_folded_task_rows() -> None:
    first = ToolCallWidget("first", "read_file")
    first.set_arguments(
        {
            "path": "one.py",
            "activity": {"reason": "Inspect UI", "group": "inspect"},
        }
    )
    first.set_result("ok")
    second = ToolCallWidget("second", "bash")
    second.set_arguments(
        {
            "command": "pytest",
            "activity": {"reason": "Run checks", "group": "validate"},
        }
    )
    second.set_result("ok")
    items = [first, second]

    reconcile_live_tools(items, final=True)

    assert len(items) == 2
    assert [item.title for item in items] == [
        "Inspect UI · 1 tool",
        "Run checks · 1 tool",
    ]


def test_activity_reason_labels_live_tool_and_folded_summary() -> None:
    widget = ToolCallWidget("read", "read_file")
    widget.set_arguments(
        {
            "path": "src/app.py",
            "activity": {
                "reason": "Trace the task UI",
                "group": "task-ui",
            },
        }
    )

    assert widget.arguments == {"path": "src/app.py"}
    assert widget.activity_reason == "Trace the task UI"
    assert widget.activity_group == "task-ui"
    assert widget._header_values == ("Read", "Trace the task UI", "preparing")

    widget.status = "done"
    summary = ToolCallSummary((widget.snapshot(),))
    assert summary.title == "Trace the task UI · 1 tool"
    assert summary.render().plain == "[ Trace the task UI · 1 tool ]"


def test_flattened_activity_aliases_are_accepted_and_stripped() -> None:
    widget = ToolCallWidget("search", "search")
    widget.set_arguments(
        {
            "query": "ToolCallWidget",
            "verb": "Searching",
            "goal": "Find the rendering path",
            "group": "task-ui",
        },
        '{"query":"ToolCallWidget","verb":"Searching","goal":"Find the rendering path","group":"task-ui"}',
    )

    assert widget.arguments == {"query": "ToolCallWidget"}
    assert widget.activity_verb == "Searching"
    assert widget.activity_reason == "Find the rendering path"
    assert widget.activity_group == "task-ui"
    assert widget.raw_arguments == '{"query":"ToolCallWidget"}'


def test_snapshot_extracts_activity_without_showing_it_as_tool_arguments() -> None:
    snapshot = snapshot_from_call(
        call_id="search",
        tool_name="search",
        arguments={
            "query": "ToolCallWidget",
            "activity": {
                "reason": "Find the rendering path",
                "group": "task-ui",
            },
        },
    )

    assert snapshot.detail == "ToolCallWidget"
    assert snapshot.activity_reason == "Find the rendering path"
    assert snapshot.activity_group == "task-ui"
    summary = ToolCallSummary((snapshot,))
    assert summary.title == "Find the rendering path · 1 tool"


def test_activity_reasons_without_group_fold_together() -> None:
    first = ToolCallWidget("first", "read_file")
    first.set_arguments({"path": "one.py", "activity": {"reason": "Inspect UI"}})
    first.set_result("ok")
    second = ToolCallWidget("second", "bash")
    second.set_arguments({"command": "pytest", "activity": {"reason": "Run checks"}})
    second.set_result("ok")
    items = [first, second]

    reconcile_live_tools(items, final=True)

    assert len(items) == 1
    assert items[0].call_ids == ["first", "second"]
    assert items[0].title == "Inspect UI · 2 tools"


def test_labeled_and_unlabeled_calls_do_not_share_an_explored_row() -> None:
    labeled = ToolCallWidget("labeled", "read_file")
    labeled.set_arguments({"path": "one.py", "activity": {"reason": "Inspect UI"}})
    labeled.set_result("ok")
    unlabeled = ToolCallWidget("plain", "bash")
    unlabeled.set_arguments({"command": "pytest"})
    unlabeled.set_result("ok")
    items = [labeled, unlabeled]

    reconcile_live_tools(items, final=True)

    assert [item.call_ids for item in items] == [["labeled"], ["plain"]]


def test_same_activity_group_keys_on_group_then_bool_reason() -> None:
    inspect = ToolCallSnapshot("a", activity_reason="Inspect UI", activity_group="inspect")
    validate = ToolCallSnapshot("b", activity_reason="Run checks", activity_group="validate")
    reason_a = ToolCallSnapshot("c", activity_reason="Inspect UI")
    reason_b = ToolCallSnapshot("d", activity_reason="Run checks")
    plain = ToolCallSnapshot("e")

    assert not same_activity_group(inspect, validate)
    assert same_activity_group(reason_a, reason_b)
    assert not same_activity_group(reason_a, plain)
    assert same_activity_group(plain, ToolCallSnapshot("f"))


def test_completed_run_summary_renders_unbracketed_verb_and_duration() -> None:
    summary = CompletedRunSummary(verb="Stargazed", duration="2m 2s")
    rendered = summary.render().plain
    assert rendered == "Stargazed for 2m 2s"
    assert "[" not in rendered
    assert "]" not in rendered


def test_completed_run_summary_picks_a_claude_style_verb() -> None:
    summary = CompletedRunSummary(duration="10s")
    rendered = summary.render().plain
    assert rendered.endswith(" for 10s")
    assert rendered[: -len(" for 10s")] in COMPLETION_VERBS


def test_explored_title_appends_duration_only_when_verb_is_set() -> None:
    with_verb = ToolCallSnapshot(
        "search",
        activity_verb="Searching",
        activity_reason="Find the path",
        duration=1.5,
    )
    reason_only = ToolCallSnapshot("read", activity_reason="Find the path", duration=1.5)

    assert ToolCallSummary((with_verb,)).title == "Searching · 1 tool for 1.5s"
    assert ToolCallSummary((reason_only,)).title == "Find the path · 1 tool"
    assert format_explored_duration((with_verb,)) == "1.5s"
    assert format_explored_duration((reason_only,)) == ""


def test_thought_snapshot_keeps_collapsed_preview() -> None:
    summary = ToolCallSummary()
    summary.add_thought("[ Thought for Inspecting files ]", "Private reasoning body")

    collapsed = summary.render().plain
    assert "Private reasoning body" in collapsed
    assert "[ Thought for Inspecting files ]" not in collapsed

    summary.toggle()
    expanded = summary.render().plain
    assert "[ Thought for Inspecting files ]" in expanded
    assert "Private reasoning body" in expanded


def test_motion_helpers_are_safe_without_an_app() -> None:
    summary = ToolCallSummary()
    settle_row(summary)
    enter_row(summary)
    assert summary.styles.opacity == 1.0
