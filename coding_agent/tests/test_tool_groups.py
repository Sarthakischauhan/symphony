"""Unit tests for the render-time tool group (no full TUI App)."""

from __future__ import annotations

import asyncio

import pytest
from textual.app import App

from coding_agent.tui.tools.activity import COMPLETION_VERBS
from coding_agent.tui.tools.kinds import CountedCall, counted_label
from coding_agent.tui.tools.calls import (
    LIVE_OUTPUT_TAIL_LINES,
    BashToolWidget,
    ToolCallWidget,
    make_tool_widget,
)
from coding_agent.tui.tools.snapshots import (
    CompletedRunSummary,
    ThoughtSnapshot,
    ToolCallSnapshot,
    ToolCallSummary,
    snapshot_from_call,
    verb_component,
)
from coding_agent.tui.transcript.messages import AssistantMessage


def _call(call_id: str, label: str = "Read", status: str = "done", **fields: str) -> ToolCallSnapshot:
    fields.setdefault("tool_name", "read_file")
    return ToolCallSnapshot(call_id, label=label, detail=f"{call_id}.py", status=status, **fields)


def test_bulk_summary_builds_metadata_once_and_preserves_entry_order(monkeypatch) -> None:
    calls = 0
    original = ToolCallSummary._summary_title

    def counted(self):
        nonlocal calls
        calls += 1
        return original(self)

    monkeypatch.setattr(ToolCallSummary, "_summary_title", counted)
    first = _call("first")
    thought = ThoughtSnapshot("Thinking", "Inspect the tools")
    failed = _call("last", status="failed")
    entries = [first, thought, first, *(_call(str(i)) for i in range(1000)), failed]
    summary = ToolCallSummary(entries)

    assert calls == 1
    assert summary.count == 1002
    assert summary.entries == [first, thought, *entries[3:]]
    assert summary.has_class("has-failures")
    assert "1 failed" in summary.title
    summary.update_call(_call("last"))
    assert not summary.has_class("has-failures")


def test_group_line_uses_subtle_explored_and_muted_count() -> None:
    summary = ToolCallSummary((_call("read-0"), _call("read-1")))
    assert summary.title == "Read 2 files"
    assert summary.render().plain == "Read 2 files"


def test_live_group_starts_expanded_and_folds_on_close() -> None:
    summary = ToolCallSummary(expanded=True)
    summary.add_call(_call("read-0", status="running"))
    assert summary.is_expanded
    assert "└ Read read-0.py" in summary.render().plain

    summary.close()
    assert not summary.is_expanded
    assert summary.render().plain == "Reading 1 file"


def test_close_never_folds_a_group_the_reader_opened() -> None:
    summary = ToolCallSummary((_call("read-0"),))
    summary.toggle()
    assert summary.user_expanded
    summary.close()
    assert summary.is_expanded

    summary.toggle()
    assert not summary.user_expanded
    assert not summary.is_expanded


def test_update_call_swaps_the_row_in_place() -> None:
    summary = ToolCallSummary((_call("read-0", status="running"), _call("read-1")), expanded=True)
    summary.update_call(_call("read-0", status="failed"))

    assert summary.call_ids == ["read-0", "read-1"]
    assert [call.status for call in summary.calls] == ["failed", "done"]
    assert summary.entries == summary.calls
    assert summary.has_class("has-failures")
    assert "1 failed" in summary.render().plain


def test_add_call_ignores_a_repeated_call_id() -> None:
    summary = ToolCallSummary()
    summary.add_call(_call("read-0"))
    summary.add_call(_call("read-0"))
    assert summary.count == 1


def test_remove_call_drops_the_row() -> None:
    summary = ToolCallSummary((_call("read-0"), _call("read-1")))
    summary.remove_call("read-0")
    assert summary.call_ids == ["read-1"]
    assert summary.title == "Read 1 file"


def test_header_leads_with_the_latest_step_and_falls_back_to_counting() -> None:
    first = _call("a", activity_verb="Reading", activity_reason="Find the loader")
    later = _call("b", label="Search", tool_name="search", activity_verb="Searching", activity_reason="Trace its callers")
    summary = ToolCallSummary((first,))
    assert summary.render().plain == "Reading · Find the loader"
    summary.add_call(later)
    # The header follows the model's latest step; earlier steps are in the rows.
    assert summary.render().plain == "Searching · Trace its callers"
    assert summary.title == "Searching · Trace its callers"
    # Unlabelled calls fall back to counting the work.
    assert ToolCallSummary((_call("c"), _call("d"))).render().plain == "Read 2 files"


def test_running_heading_shimmers_and_settles_when_done() -> None:
    summary = ToolCallSummary((_call("a", status="running", activity_verb="Reading"),))
    assert summary.running
    colors = {span.style for span in summary.render().spans if span.end <= len("Reading")}
    assert len(colors) > 1  # a gradient across the verb
    summary._advance_shimmer()
    assert {span.style for span in summary.render().spans if span.end <= len("Reading")} != colors or len(colors) > 1
    summary.update_call(_call("a", activity_verb="Reading"))
    assert not summary.running
    assert {str(span.style) for span in summary.render().spans} == {"bold #8ab4cf"}


def test_groups_fold_exploring_calls_whatever_their_activity() -> None:
    inspect = _call("a", activity_reason="Inspect UI", activity_group="inspect")
    summary = ToolCallSummary((inspect,))

    # Activity no longer splits a run of reads and searches.
    assert summary.accepts(_call("b", label="Search", tool_name="search", activity_group="validate"))
    # Actions keep their own card, so a group never takes one.
    assert not summary.accepts(_call("c", label="Update", tool_name="patch"))
    assert not summary.accepts(_call("d", label="Bash", tool_name="bash"))
    assert ToolCallSummary().accepts(_call("e"))


def test_read_header_uses_protocol_path_without_slash() -> None:
    widget = make_tool_widget("read-1", "read_file")
    widget.set_arguments({"path": "history.py"})
    widget.refresh_content()
    assert widget._header_values == ("Read", "history.py", "preparing")

    widget.set_arguments({}, '{"path":"labels.py"')
    widget.refresh_content()
    assert widget._header_values is not None
    assert widget._header_values[1] == "labels.py"


def test_group_discloses_call_snapshots_only_when_expanded() -> None:
    widget = make_tool_widget("read-1", "read_file")
    widget.set_arguments({"path": "src/app.py"})
    widget.set_result("line one\nline two")
    summary = ToolCallSummary()
    summary.add_call(widget.snapshot())

    assert "src/app.py" not in summary.render().plain
    summary.toggle()

    rendered = summary.render().plain
    assert rendered.startswith("Read 1 file")
    assert "Read app.py" in rendered
    assert "Read 2 lines (17 bytes)" not in rendered
    assert summary.snapshot_text() == "✓  Read  src/app.py\n   Read 2 lines (17 bytes)"


def test_expanded_summary_rows_hang_off_an_fx_tree_guide() -> None:
    summary = ToolCallSummary(
        (
            ToolCallSnapshot("read-1", tool_name="read_file", label="Read", detail="src/app.py"),
            ThoughtSnapshot(title="Thought 1.2s", content="Checking the loader."),
            ToolCallSnapshot("grep-1", tool_name="search", label="Search", detail="loader", status="running"),
            ToolCallSnapshot("bash-1", tool_name="bash", label="Bash", detail="pytest -q", status="failed"),
        )
    )
    summary.toggle()

    header, *rows = summary.render().plain.split("\n")
    assert header == "Reading 1 file, Searching 1 pattern, Running 1 command · 1 failed"
    # The guide sits at the header's left edge: "├" per row, "│" under a
    # continued row, "└" on the last row; then verb and args, no status dot.
    assert rows == [
        "├ Read app.py",
        "├ Thought 1.2s",
        "│ Checking the loader.",
        "├ Search loader",
        "└ Bash pytest -q",
    ]


@pytest.mark.parametrize(
    ("status", "component"),
    [
        ("done", "tool-call-summary--verb"),
        ("failed", "tool-call-summary--verb-failed"),
        ("running", "tool-call-summary--verb-running"),
        ("preparing", "tool-call-summary--verb-running"),
    ],
)
def test_nested_row_verb_colour_follows_call_status(status: str, component: str) -> None:
    assert verb_component(status) == component


def test_patch_header_recovers_path_when_arguments_are_missing() -> None:
    widget = make_tool_widget("patch-empty", "patch")
    widget.set_arguments({})
    widget.set_running({})
    widget.set_result("patched src/coding_agent/tui/screens/history.py (1 replacement(s), +0 -1)")

    assert "history.py" in widget._summary()
    assert widget._header_values is not None
    assert widget._header_values[0] == "Update"
    assert "history.py" in widget._header_values[1]


def test_patch_snapshot_keeps_update_target_and_stats() -> None:
    widget = make_tool_widget("patch-1", "patch")
    widget.set_arguments({
        "path": "src/labels.py",
        "old_str": "old\\n",
        "new_str": "new\\n",
    })
    widget.set_result("patched src/labels.py (1 replacement(s), +4 bytes)")
    summary = ToolCallSummary((widget.snapshot(),))
    summary.toggle()

    rendered = summary.render().plain
    assert "Update labels.py +1 -1" in rendered
    assert "Update\\n" not in rendered


@pytest.mark.parametrize(
    ("result", "filename"),
    [
        ("patched coding_agent/src/coding_agent/tui/transcript/process.py (1 replacement(s), +0 bytes)", "process.py"),
        ("updated src/app.py", "app.py"),
        ("noop: old_str and new_str are identical in src/app.py; no change", "app.py"),
        ("old_str not found in src/app.py", "app.py"),
        ("error: file not found: src/app.py", "app.py"),
    ],
)
def test_patch_result_fallback_names_the_file(result: str, filename: str) -> None:
    widget = make_tool_widget("patch-result", "patch")
    widget.set_result(result)
    assert filename in widget._summary()
    snapshot = snapshot_from_call(call_id="patch-result", tool_name="patch", result=result)
    assert filename in snapshot.detail


def test_cards_and_group_rows_split_by_tool() -> None:
    for tool_name in ("generate_image", "bash", "patch"):
        assert make_tool_widget("card", tool_name).keep_in_transcript
    for tool_name in ("read_file", "search"):
        assert not make_tool_widget("row", tool_name).keep_in_transcript


def test_summary_keeps_failures_visible_when_collapsed() -> None:
    summary = ToolCallSummary()
    summary.add_call(ToolCallSnapshot("failed", status="failed", result="Permission denied"))

    assert "1 failed" in summary.render().plain
    assert summary.has_class("has-failures")
    summary.toggle()
    assert "Permission denied" not in summary.render().plain


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


def test_activity_reason_labels_tool_and_group() -> None:
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
    assert widget._header_values == ("Read", "app.py", "preparing")

    widget.status = "done"
    summary = ToolCallSummary((widget.snapshot(),))
    # The header says why, in the model's words; the row below says what.
    assert summary.title == "Trace the task UI"
    assert summary.render().plain == "Trace the task UI"


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
    assert summary.title == "Find the rendering path"


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


def test_counted_label_names_kinds_in_order_and_counts_distinct_files() -> None:
    calls = [
        CountedCall("read_file", path="a.py"),
        CountedCall("read_file", path="a.py"),
        CountedCall("read_file", path="b.py"),
        CountedCall("search"),
        CountedCall("patch", path="a.py"),
        CountedCall("patch", path="a.py"),
        CountedCall("bash", failed=True),
    ]
    assert counted_label(calls) == ("Read 2 files, Searched 1 pattern, Edited 1 file, Ran 1 command", False, 1)
    # Present tense while anything in the run is still going.
    running = [CountedCall("read_file", path="a.py"), CountedCall("bash", running=True)]
    assert counted_label(running)[0] == "Reading 1 file, Running 1 command"
    # A tool without its own words still counts.
    assert counted_label([CountedCall("mcp__notes__find")])[0] == "Ran 1 tool"


def test_thought_snapshot_keeps_collapsed_preview() -> None:
    summary = ToolCallSummary()
    summary.add_thought("Thought Inspecting files", "Private reasoning body")

    collapsed = summary.render().plain
    assert "Private reasoning body" in collapsed
    assert "Thought Inspecting files" not in collapsed

    summary.toggle()
    expanded = summary.render().plain
    assert "Thought Inspecting files" in expanded
    assert "Private reasoning body" in expanded


def test_bash_tail_joins_partial_lines_and_keeps_the_newest() -> None:
    async def _run() -> None:
        # Static.update needs an active app to build its visual.
        async with App().run_test():
            card = BashToolWidget("bash-1", "bash")
            card.set_running({"command": "pytest -q"})
            card.append_output("one\ntw")
            card.append_output("o\nthree")
            assert [line for _stream, line in card._live_tail()] == ["one", "two", "three"]

            for line in range(LIVE_OUTPUT_TAIL_LINES + 3):
                card.append_output(f"line {line}\n")
            assert [line for _stream, line in card._live_tail()] == [
                f"line {line}" for line in range(3, LIVE_OUTPUT_TAIL_LINES + 3)
            ]

            card.set_result("12 passed")
            assert card._live_tail() == []

    asyncio.run(_run())
