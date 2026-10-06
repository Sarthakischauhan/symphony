"""Finished turns freeze into one widget that paints their rendered lines."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from rich.segment import Segment
from textual.pilot import Pilot

from coding_agent.tui.app import CodingAgentApp
from coding_agent.tui.composer import QueuedTurn
from coding_agent.tui.tools import ToolCallSummary
from coding_agent.tui.transcript import TranscriptScroll
from coding_agent.tui.transcript.process import RunProcess

SIZE = (100, 30)


def _app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> CodingAgentApp:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = CodingAgentApp(workspace=tmp_path)
    monkeypatch.setattr(app, "run_agent", lambda content: None)
    return app


def _read(app: CodingAgentApp, call_id: str) -> None:
    app.add_tool(call_id, "read_file")
    app.update_tool(call_id, arguments={"path": f"src/{call_id}.py"}, status="running")
    app.update_tool(call_id, status="done", result="ok")


def _turn(app: CodingAgentApp, index: int) -> RunProcess:
    """One turn: a thought, an Explored group, a Bash card, a group row, the reply."""
    app._start_turn(QueuedTurn(f"question {index}", f"question {index}", (), ()))
    app.set_reasoning(f"**Plan {index}**\n\nRead the loader, then run the tests.")
    app.finish_reasoning()
    for call in range(3):
        _read(app, f"{index}-read-{call}")
    app.add_tool(f"{index}-bash", "bash")
    app.update_tool(f"{index}-bash", arguments={"command": "pytest -q"}, status="running")
    app.update_tool(f"{index}-bash", status="done", result="3 passed")
    _read(app, f"{index}-read-last")
    app.set_assistant(f"Answer {index}.\n\n- first point\n- second point", new=True)
    app.finish_assistant()
    assert app._process is not None
    return app._process


async def _finish(app: CodingAgentApp, pilot: Pilot[None]) -> RunProcess:
    process = app._process
    assert process is not None
    app.finish_process("1s (↑1k ↓200) · 1 model call · 5 tool calls")
    await pilot.pause()
    await pilot.pause()  # mounted and laid out, then frozen
    assert process.frozen
    return process


def _transcript_lines(app: CodingAgentApp) -> list[list[Segment]]:
    """The transcript's rows exactly as painted on screen."""
    region = app.query_one("#transcript", TranscriptScroll).region
    strips = app.screen._compositor.render_strips()
    return [list(strip.crop(region.x, region.right)) for strip in strips[region.y : region.bottom]]


def _text(lines: list[list[Segment]]) -> str:
    return "\n".join("".join(segment.text for segment in line) for line in lines)


def test_freeze_leaves_one_widget_per_finished_turn(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    app = _app(monkeypatch, tmp_path)

    async def _run() -> None:
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            counts: list[int] = []
            for index in range(3):
                _turn(app, index)
                await pilot.pause()
                live = len(list(app.screen.walk_children()))
                await _finish(app, pilot)
                counts.append(len(list(app.screen.walk_children())))
                assert counts[-1] < live
            runs = list(app.query(RunProcess))
            assert len(runs) == 3
            assert all(run.frozen and not run.children for run in runs)
            # Each finished turn adds only its prompt and its frozen run.
            assert counts[2] - counts[1] == counts[1] - counts[0] == 2

    asyncio.run(_run())


def test_frozen_run_paints_the_live_render_without_moving_the_scroll(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = _app(monkeypatch, tmp_path)

    async def _run() -> None:
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            for index in range(2):
                _turn(app, index)
                await _finish(app, pilot)
            process = _turn(app, 2)
            process.complete("1s · 1 model call · 5 tool calls")  # finished, not yet frozen
            await pilot.pause()
            transcript = app.query_one("#transcript", TranscriptScroll)
            assert transcript.max_scroll_y > 0

            # Anchored at the bottom, then scrolled up into the run.
            for scroll_y in (transcript.max_scroll_y, transcript.max_scroll_y - 8):
                await process.thaw()
                await pilot.pause()
                transcript.scroll_to(y=scroll_y, animate=False)
                await pilot.pause()
                live = _transcript_lines(app)
                height = process.region.height
                process.freeze()
                await pilot.pause()
                assert process.frozen and not process.children
                assert process.region.height == height
                assert transcript.scroll_y == scroll_y
                assert _transcript_lines(app) == live

    asyncio.run(_run())


def test_clicking_a_group_in_a_frozen_turn_remounts_and_toggles_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = _app(monkeypatch, tmp_path)

    async def _run() -> None:
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            _turn(app, 0)
            group = app._tool_groups["0-read-0"]
            process = await _finish(app, pilot)
            assert not group.is_attached
            assert not group.is_expanded  # the Bash card folded it

            region = app.query_one("#transcript", TranscriptScroll).region
            lines = _text(_transcript_lines(app)).splitlines()
            row = next(y for y, line in enumerate(lines) if "Explored · 3 tools" in line)
            await pilot.click(offset=(region.x + lines[row].index("Explored"), region.y + row))
            await pilot.pause()

            assert not process.frozen
            assert group.is_attached
            assert group.is_expanded
            assert app.query(ToolCallSummary).first() is group
            assert "├ Read" in _text(_transcript_lines(app))

    asyncio.run(_run())


def test_an_expanded_group_stays_expanded_through_freeze(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    app = _app(monkeypatch, tmp_path)

    async def _run() -> None:
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            _turn(app, 0)
            await pilot.pause()
            group = app._tool_groups["0-read-0"]
            await pilot.click(group)
            assert group.is_expanded

            process = await _finish(app, pilot)
            frozen = _text(_transcript_lines(app))
            assert "├ Read 0-read-0.py" in frozen
            assert "└ Read 0-read-2.py" in frozen

            await process.thaw()
            await pilot.pause()
            assert group.is_expanded

    asyncio.run(_run())


def test_a_frozen_run_renders_again_at_a_new_width(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    app = _app(monkeypatch, tmp_path)

    async def _run() -> None:
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            _turn(app, 0)
            process = await _finish(app, pilot)
            await pilot.resize_terminal(72, 30)
            await pilot.pause()
            await pilot.pause()
            assert process.frozen
            frozen = _transcript_lines(app)
            await process.thaw()
            await pilot.pause()
            assert _transcript_lines(app) == frozen

    asyncio.run(_run())
