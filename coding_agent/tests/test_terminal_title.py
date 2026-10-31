"""The TUI names the terminal tab "Symphony" and restores the previous title on exit."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from textual.drivers.headless_driver import HeadlessDriver

from coding_agent import cli
from coding_agent.tui.app import CodingAgentApp
from coding_agent.tui.terminal_title import POP_TITLE, PUSH_TITLE, SET_TITLE


def test_terminal_title_sequences_are_the_xterm_ones() -> None:
    assert PUSH_TITLE == "\x1b[22;0t"
    assert SET_TITLE == "\x1b]0;Symphony\x07"
    assert POP_TITLE == "\x1b[23;0t"


def test_tui_pushes_and_sets_title_on_mount_and_pops_on_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    written: list[str] = []
    monkeypatch.setattr(HeadlessDriver, "write", lambda self, data: written.append(data))
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            assert PUSH_TITLE + SET_TITLE in written
            assert POP_TITLE not in written
            await pilot.press("ctrl+q")
            await pilot.pause()

    asyncio.run(_run())

    assert written.index(PUSH_TITLE + SET_TITLE) < written.index(POP_TITLE)
    assert written.count(PUSH_TITLE + SET_TITLE) == 1
    assert written.count(POP_TITLE) == 1


def test_cli_entry_names_the_process_symphony(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    titles: list[str] = []
    monkeypatch.setattr(cli, "setproctitle", titles.append)
    monkeypatch.setattr(cli.sys, "argv", ["symphony", "--version"])

    cli.main()

    assert titles == ["symphony"]
    assert capsys.readouterr().out.startswith("symphony ")
