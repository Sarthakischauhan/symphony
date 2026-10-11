"""``/diff`` and the ``@`` file index do their disk work off the Textual UI thread.

Each test blocks the git or walk call on an event. The UI loop must keep
painting meanwhile (the pilot keeps getting turns), the blocked call must be
on another thread, and the result must land once the call is released.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

from coding_agent.tui.app import CodingAgentApp
from coding_agent.tui.composer import SlashMenu
from coding_agent.tui.screens import DiffModal
from coding_agent.tui.screens.diff import DiffFileCard
from coding_agent.tui.screens import file_selector

DIFF = (
    "diff --git a/src/app.py b/src/app.py\n"
    "--- a/src/app.py\n"
    "+++ b/src/app.py\n"
    "@@ -1 +1,2 @@\n"
    "-old\n"
    "+new\n"
    "+added\n"
)


class Blocked:
    """Stand-in for a slow call: records its thread, waits to be released."""

    def __init__(self, result) -> None:  # type: ignore[no-untyped-def]
        self.result = result
        self.release = threading.Event()
        self.entered = threading.Event()
        self.threads: list[threading.Thread] = []

    def __call__(self, *_args):  # type: ignore[no-untyped-def]
        self.threads.append(threading.current_thread())
        self.entered.set()
        assert self.release.wait(10), "test never released the call"
        return self.result() if callable(self.result) else self.result


async def _entered(blocked: Blocked) -> None:
    await asyncio.to_thread(blocked.entered.wait, 5)
    assert blocked.entered.is_set()


def test_diff_runs_git_in_a_worker_and_paints_a_loading_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    git = Blocked(DIFF)
    monkeypatch.setattr("coding_agent.tui.screens.diff.read_workspace_diff", git)
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            app.push_screen(DiffModal(tmp_path))
            await _entered(git)
            await pilot.pause()
            # git is still running, yet the modal mounted and keeps painting.
            assert isinstance(app.screen, DiffModal)
            assert app.screen.query("#diff-loading")
            assert not app.screen.query(DiffFileCard)
            assert git.threads[0] is not threading.main_thread()

            git.release.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            card = app.screen.query_one(DiffFileCard)
            assert (card.path, card.additions, card.deletions) == ("src/app.py", 2, 1)
            assert not app.screen.query("#diff-loading")
            assert "1 of 1 files" in str(app.screen.query_one("#diff-file-counter").render())

    asyncio.run(_run())


def test_diff_closed_while_git_runs_drops_the_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    git = Blocked(DIFF)
    monkeypatch.setattr("coding_agent.tui.screens.diff.read_workspace_diff", git)
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            modal = DiffModal(tmp_path)
            app.push_screen(modal)
            await _entered(git)
            app.pop_screen()
            await pilot.pause()
            git.release.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert not isinstance(app.screen, DiffModal)
            assert not modal._cards

    asyncio.run(_run())


def test_clean_tree_still_says_so(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "coding_agent.tui.screens.diff.read_workspace_diff", lambda _workspace: "No local changes found."
    )
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            app.push_screen(DiffModal(tmp_path))
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            group = app.screen.query_one(".empty-state").render()._renderable
            assert "Working tree is clean" in [text.plain for text in group.renderables]
            assert "0 files" in str(app.screen.query_one("#diff-file-counter").render())

    asyncio.run(_run())


def test_at_mention_walks_the_workspace_in_a_worker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "turn.py").write_text("pass\n", encoding="utf-8")
    real_scan = file_selector._scan_workspace
    walk = Blocked(lambda: real_scan(tmp_path))
    monkeypatch.setattr(file_selector, "_scan_workspace", walk)
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            prompt = app.query_one("#prompt")
            prompt.value = "Review @tur"
            await _entered(walk)
            await pilot.pause()
            # The walk is blocked; typing still works.
            prompt.value = "Review @turn"
            await pilot.pause()
            assert prompt.value == "Review @turn"
            assert walk.threads[0] is not threading.main_thread()

            walk.release.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            menu = app.query_one("#slash-menu", SlashMenu)
            assert menu.display and menu.is_file_selector
            assert menu.selected_value == "@src/turn.py"
            assert len(walk.threads) == 1  # one walk, not one per keystroke

    asyncio.run(_run())


def test_stale_index_serves_the_last_walk_while_it_rebuilds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "old.py").write_text("pass\n", encoding="utf-8")
    real_scan = file_selector._scan_workspace
    app = CodingAgentApp(workspace=tmp_path)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            prompt = app.query_one("#prompt")
            menu = app.query_one("#slash-menu", SlashMenu)
            prompt.value = "@"
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert [option.path for option in menu._files] == ["old.py"]
            prompt.value = ""
            await pilot.pause()

            (tmp_path / "new.py").write_text("pass\n", encoding="utf-8")
            app.invalidate_workspace_caches()  # what write_file/patch/bash trigger
            walk = Blocked(lambda: real_scan(tmp_path))
            monkeypatch.setattr(file_selector, "_scan_workspace", walk)
            prompt.value = "@"
            await _entered(walk)
            await pilot.pause()
            assert [option.path for option in menu._files] == ["old.py"]

            walk.release.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert sorted(option.path for option in menu._files) == ["new.py", "old.py"]

    asyncio.run(_run())


def test_index_invalidated_mid_walk_is_not_marked_fresh(tmp_path: Path, monkeypatch) -> None:
    index = file_selector.WorkspaceFileIndex(tmp_path)
    real_scan = file_selector._scan_workspace

    def scan_then_invalidate(workspace: Path):  # type: ignore[no-untyped-def]
        entries = real_scan(workspace)
        index.invalidate()
        return entries

    monkeypatch.setattr(file_selector, "_scan_workspace", scan_then_invalidate)
    assert index.rebuild() is False
    assert not index.fresh
    assert index.cached_matches("") == ()
    monkeypatch.setattr(file_selector, "_scan_workspace", real_scan)
    assert index.rebuild() is True and index.fresh
