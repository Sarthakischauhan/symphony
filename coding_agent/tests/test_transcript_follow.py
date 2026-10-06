"""The live transcript follows its tail, respects a scrolled-up reader, and
updates rows in place instead of remounting them."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.pilot import Pilot
from textual.widget import Widget

from coding_agent.tui.app import CodingAgentApp
from coding_agent.tui.composer import QueuedTurn
from coding_agent.tui.tools import CompletedRunSummary, GenerateImageWidget, ToolCallSummary
from coding_agent.tui.transcript import AssistantMessage, TranscriptScroll, UserMessage

SIZE = (100, 30)


def _app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> CodingAgentApp:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return CodingAgentApp(workspace=tmp_path)


def _read(app: CodingAgentApp, call_id: str, status: str = "done") -> None:
    app.add_tool(call_id, "read_file")
    app.update_tool(call_id, arguments={"path": f"src/{call_id}.py"}, status="running")
    if status != "running":
        app.update_tool(call_id, status=status, result="ok")


def _stream_step(app: CodingAgentApp, step: int) -> None:
    """One streamed update; a cycle of thinking, tool rows and assistant text."""
    phase = step % 10
    if phase < 3:
        app.set_reasoning(f"Weighing option {step}. " * (phase + 1), new=phase == 0)
    elif phase == 3:
        app.finish_reasoning()
        _read(app, f"read-{step}", status="running")
    elif phase < 7:
        app.update_tool(f"read-{step - phase + 3}", status="done", result="ok")
        _read(app, f"read-{step}")
    else:
        app.set_assistant(f"Progress note {step}. " * (phase - 5), new=phase == 7)
        if phase == 9:
            app.finish_assistant()


async def _overflowing_run(app: CodingAgentApp, pilot: Pilot[None]) -> TranscriptScroll:
    transcript = app.query_one("#transcript", TranscriptScroll)
    app.mount_transcript(UserMessage("trace the render loop"))
    for step in range(40):
        _stream_step(app, step)
    await pilot.pause()
    assert transcript.max_scroll_y > 10
    return transcript


def _timeline(app: CodingAgentApp) -> list[Widget]:
    assert app._process is not None
    return list(app._process.children)


def test_follow_stays_at_the_bottom_over_100_streamed_updates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = _app(monkeypatch, tmp_path)

    async def _run() -> None:
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            transcript = app.query_one("#transcript", TranscriptScroll)
            app.mount_transcript(UserMessage("trace the render loop"))
            missed = []
            for step in range(100):
                _stream_step(app, step)
                await pilot.pause()
                if transcript.scroll_offset.y != transcript.max_scroll_y:
                    missed.append(step)
            assert missed == []
            assert transcript.max_scroll_y > 0
            assert transcript.scroll_y == transcript.max_scroll_y

    asyncio.run(_run())


def test_scrolled_up_reader_stays_put_while_rows_append_and_groups_fold(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = _app(monkeypatch, tmp_path)

    async def _run() -> None:
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            transcript = await _overflowing_run(app, pilot)
            transcript.scroll_to(y=5, animate=False)
            await pilot.pause()
            assert transcript.scroll_y == 5

            for index in range(6):
                _read(app, f"late-{index}")
                await pilot.pause()
                assert transcript.scroll_y == 5
            group = list(app.query(ToolCallSummary))[-1]
            assert group.is_expanded
            app.set_assistant("The late reads are done.", new=True)
            await pilot.pause()
            assert not group.is_expanded
            assert transcript.scroll_y == 5

            # Back at the end, the anchor re-engages and follows again.
            transcript.scroll_end(animate=False)
            await pilot.pause()
            for index in range(6):
                _read(app, f"tail-{index}")
                await pilot.pause()
                assert transcript.scroll_y == transcript.max_scroll_y

    asyncio.run(_run())


def test_run_end_keeps_intermediate_text_and_user_expanded_groups(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = _app(monkeypatch, tmp_path)

    async def _run() -> None:
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            app.mount_transcript(UserMessage("fix the scroll"))
            for index in range(3):
                _read(app, f"a-{index}")
            app.set_assistant("Found the follow logic.", new=True)
            app.finish_assistant()
            await pilot.pause()
            opened = app.query_one(ToolCallSummary)
            assert not opened.is_expanded
            await pilot.click(opened)
            assert opened.is_expanded

            for index in range(2):
                _read(app, f"b-{index}")
            app.set_assistant("Anchored the transcript instead.", new=True)
            app.finish_assistant()
            await pilot.pause()
            before = _timeline(app)

            app.finish_process("12s · 3 model calls · 5 tool calls")
            await pilot.pause()

            after = _timeline(app)
            assert after[: len(before)] == before
            assert not list(app.query(CompletedRunSummary))
            assert [message.message_text for message in app.query(AssistantMessage)] == [
                "Found the follow logic.",
                "Anchored the transcript instead.",
            ]
            first, second = app.query(ToolCallSummary)
            assert first is opened
            assert first.is_expanded
            assert not second.is_expanded

    asyncio.run(_run())


def test_running_to_done_changes_text_without_remounting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = _app(monkeypatch, tmp_path)

    async def _run() -> None:
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            app.mount_transcript(UserMessage("draw and inspect"))
            _read(app, "read-1", status="running")
            app.add_tool("image-1", "generate_image")
            app.update_tool("image-1", arguments={"prompt": "a lighthouse"}, status="running")
            await pilot.pause()
            group = app.query_one(ToolCallSummary)
            card = app.query_one(GenerateImageWidget)
            before = _timeline(app)
            running_text = group.render().plain

            app.update_tool("read-1", status="done", result="ok")
            app.update_tool("image-1", status="done", result="saved lighthouse.png")
            await pilot.pause()

            assert _timeline(app) == before
            assert app.query_one(ToolCallSummary) is group
            assert app.query_one(GenerateImageWidget) is card
            assert group.calls[0].status == "done"
            assert card.status == "done"
            assert group.render().plain == running_text

    asyncio.run(_run())


def test_a_new_turn_starts_fresh_tool_groups(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = _app(monkeypatch, tmp_path)
    monkeypatch.setattr(app, "run_agent", lambda content: None)

    async def _run() -> None:
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            app._start_turn(QueuedTurn("first", "first", (), ()))
            _read(app, "call-0")
            app.finish_process("done")
            await pilot.pause()
            first = app.query_one(ToolCallSummary)

            # Providers may reuse call ids across runs; the new turn gets its own row.
            app._start_turn(QueuedTurn("second", "second", (), ()))
            _read(app, "call-0", status="running")
            await pilot.pause()
            groups = list(app.query(ToolCallSummary))
            assert groups[0] is first
            assert [call.status for call in first.calls] == ["done"]
            assert len(groups) == 2
            assert groups[1].parent is app._process
            assert [call.status for call in groups[1].calls] == ["running"]

    asyncio.run(_run())
