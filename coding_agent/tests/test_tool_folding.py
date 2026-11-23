"""Tool folding after Grok Build's scrollback.

Exploring calls fold under a counted header ("Read 3 files, Searched 1 pattern").
Every other call keeps a one-line card that opens in place. Past
``VISIBLE_ROWS`` rows in a run, the older rows fold behind a header that counts
them ("Edited 2 files, Ran 1 command").
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from coding_agent.tui.app import CodingAgentApp
from coding_agent.tui.tools.calls import BashToolWidget, PatchDiffWidget, ToolCallWidget
from coding_agent.tui.tools.kinds import VISIBLE_ROWS
from coding_agent.tui.tools.modal import ToolCallModal
from coding_agent.tui.tools.snapshots import CompletedRunSummary, ToolCallSummary, snapshot_from_call
from coding_agent.tui.transcript.process import RunFold


def _app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> CodingAgentApp:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return CodingAgentApp(workspace=tmp_path)


def _read(app: CodingAgentApp, call_id: str, path: str) -> None:
    app.add_tool(call_id, "read_file")
    app.update_tool(call_id, arguments={"path": path}, status="running")
    app.update_tool(call_id, status="done", result="ok")


def _edit(app: CodingAgentApp, call_id: str, path: str) -> None:
    app.add_tool(call_id, "patch")
    app.update_tool(call_id, arguments={"path": path, "old_str": "a\n", "new_str": "b\n"}, status="running")
    app.update_tool(call_id, status="done", result=f"patched {path} at line 1")


def _run_command(app: CodingAgentApp, call_id: str, command: str) -> None:
    app.add_tool(call_id, "bash")
    app.update_tool(call_id, arguments={"command": command}, status="running")
    app.update_tool(call_id, status="done", result="ok")


def test_reads_fold_under_one_counted_header_and_actions_keep_cards(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = _app(monkeypatch, tmp_path)

    async def run() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            _read(app, "r1", "src/app.py")
            _read(app, "r2", "src/app.py")
            _read(app, "r3", "src/loader.py")
            _edit(app, "e1", "src/app.py")
            _read(app, "r4", "src/app.py")
            await pilot.pause()

            groups = list(app.query(ToolCallSummary))
            # The edit ends the first run of reads; the read after it starts a new one.
            assert [group.call_ids for group in groups] == [["r1", "r2", "r3"], ["r4"]]
            # Two distinct files, and folded from the start.
            assert groups[0].render().plain == "Read 2 files"
            assert not groups[0].is_expanded
            assert [card.call_id for card in app.query(PatchDiffWidget)] == ["e1"]

    asyncio.run(run())


def test_a_long_run_folds_its_older_rows_behind_a_counted_header(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = _app(monkeypatch, tmp_path)

    async def run() -> None:
        async with app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            _run_command(app, "c0", "uv run ruff check .")
            _edit(app, "e0", "src/a.py")
            for index in range(1, VISIBLE_ROWS + 1):
                _edit(app, f"e{index}", f"src/{index}.py")
            await pilot.pause()

            fold = app.query_one(RunFold)
            cards = list(app.query(ToolCallWidget))
            hidden = [card.call_id for card in cards if not card.display]
            # Twelve rows, ten shown: the two oldest fold behind the header.
            assert hidden == ["c0", "e0"]
            assert fold.render().plain == "Ran 1 command, Edited 1 file  show"
            # The header sits above the rows it hides.
            assert fold.region.y < cards[0].region.y or not cards[0].display

            fold.toggle()
            await pilot.pause()
            assert all(card.display for card in app.query(ToolCallWidget))
            assert fold.render().plain.endswith("hide")

            app.set_assistant("Done.", new=True)
            await pilot.pause()
            # Anything other than a tool ends the run, so the next row starts a new count.
            _edit(app, "after", "src/z.py")
            await pilot.pause()
            assert len(app.query(RunFold)) == 1

    asyncio.run(run())


def test_the_run_summary_takes_every_action_and_drops_the_fold(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = _app(monkeypatch, tmp_path)

    async def run() -> None:
        async with app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            assert app._presenter is not None
            app._presenter.handle("run_started", {"run_id": "r"})
            for index in range(VISIBLE_ROWS + 2):
                _edit(app, f"e{index}", f"src/{index}.py")
            app.add_tool("w1", "write_file")
            app.update_tool("w1", arguments={"path": "notes.md", "content": "x"}, status="running")
            app.update_tool("w1", status="done", result="wrote notes.md")
            app._presenter.handle("run_completed", {"output_text": "Edited the files."})
            await pilot.pause()

            assert not list(app.query(RunFold))
            assert not list(app.query(PatchDiffWidget))
            summary = app.query_one(CompletedRunSummary)
            assert summary.call_ids == [f"e{index}" for index in range(VISIBLE_ROWS + 2)] + ["w1"]

    asyncio.run(run())


def test_a_card_opens_in_place_and_o_opens_its_details(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    app = _app(monkeypatch, tmp_path)

    async def run() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            _run_command(app, "c1", "pytest -q")
            await pilot.pause()
            card = app.query_one(BashToolWidget)
            header = card.query_one(".bash-tool-header")
            header.focus()
            await pilot.press("enter")
            await pilot.pause()
            assert not card.collapsed
            await pilot.press("o")
            await pilot.pause()
            assert isinstance(app.screen, ToolCallModal)

    asyncio.run(run())


def test_a_folded_row_reopens_its_details_from_its_record(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    app = _app(monkeypatch, tmp_path)
    snapshot = snapshot_from_call(
        call_id="old",
        tool_name="patch",
        arguments={"path": "src/app.py", "old_str": "old\n", "new_str": "new\n"},
        status="done",
        result="patched src/app.py at line 4 (1 replacement(s), +0 bytes)",
    )
    running = snapshot_from_call(call_id="live", tool_name="read_file", arguments={"path": "a.py"}, status="running")
    assert snapshot.record is not None and running.record is None

    async def run() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            group = ToolCallSummary((snapshot, running), expanded=True)
            app.mount_transcript(group)
            await pilot.pause()
            assert group.open_call(1) is False  # nothing to open while it runs
            assert group.open_call(0)
            await pilot.pause()
            assert isinstance(app.screen, ToolCallModal)
            body = app.screen.query_one("#tool-detail")
            detail = "\n".join(body.render_line(y).text for y in range(body.size.height))
            assert "+new" in detail and "-old" in detail

    asyncio.run(run())
