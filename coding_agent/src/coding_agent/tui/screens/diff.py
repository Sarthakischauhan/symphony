"""Workspace diff modal screen."""

from __future__ import annotations

import subprocess
from pathlib import Path

from rich.syntax import Syntax
from rich.text import Text
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.widgets import Static

from coding_agent.tui.screens.modal import EmptyState, ModalBase, ModalCloseButton, ModalScroll
from coding_agent.tui.theme import DIFF_MODAL_CSS, SYMPHONY_CODE_THEME
from coding_agent.tui.tools.diff import diff_stats

def read_workspace_diff(workspace: Path) -> str:
    """Return the current workspace diff, or a user-facing failure message."""
    try:
        result = subprocess.run(
            ["git", "-C", str(workspace), "diff", "--unified=0", "--", "."],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception as exc:  # noqa: BLE001
        return f"Failed to run git diff: {exc}"

    output = (result.stdout or "").strip()
    if output:
        return output
    if result.returncode != 0:
        err = (result.stderr or "").strip()
        return err or "git diff failed"
    return "No local changes found."


def split_diff(diff_text: str) -> list[tuple[str, str]]:
    """Split a Git diff into a path and body for each changed file."""
    files: list[tuple[str, str]] = []
    path = ""
    lines: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            if path:
                files.append((path, "\n".join(lines)))
            paths = line.removeprefix("diff --git ")
            path = paths.split(" b/", 1)[-1].removeprefix("b/")
            lines = []
        elif line.startswith(("index ", "--- ", "+++ ", "new file", "deleted file")):
            continue
        elif path:
            lines.append(line)

    if path:
        files.append((path, "\n".join(lines)))
    return files


class DiffFileCard(Container):
    """One changed file with a clear header, stats, and highlighted patch."""

    def __init__(self, path: str, body: str) -> None:
        self.path = path
        self.body = body
        self.additions, self.deletions = diff_stats(body.splitlines())
        super().__init__(classes="diff-file-card")

    def compose(self):  # type: ignore[no-untyped-def]
        stats = Text()
        stats.append(f"+{self.additions}", style="bold #8fc49a")
        stats.append(f"  −{self.deletions}", style="bold #df8b91")
        with Horizontal(classes="diff-file-header"):
            yield Static(Text(self.path, style="bold #d0d0d0"), classes="diff-file-path")
            yield Static(stats, classes="diff-file-stats")
        yield Static(
            Syntax(
                self.body,
                "diff",
                theme=SYMPHONY_CODE_THEME,  # type: ignore[arg-type]
                line_numbers=False,
                word_wrap=False,
            ),
            classes="diff-patch",
        )


class DiffModal(ModalBase[None]):
    """Fullscreen modal for inspecting the current git diff."""

    CSS = DIFF_MODAL_CSS
    BINDINGS = [
        Binding("escape", "close_modal", "Close", show=False, priority=True),
        Binding("n", "next_file", "Next file", show=False),
        Binding("p", "previous_file", "Previous file", show=False),
        Binding("enter", "toggle_collapse", "Collapse", show=False),
    ]

    def __init__(self, workspace: Path) -> None:
        super().__init__()
        self.workspace = workspace
        self._files: list[DiffFileCard] = []
        self._file_index = 0

    def compose(self):  # type: ignore[no-untyped-def]
        diff_text = read_workspace_diff(self.workspace)
        files = split_diff(diff_text)
        total_additions = sum(diff_stats(body.splitlines())[0] for _path, body in files)
        total_deletions = sum(diff_stats(body.splitlines())[1] for _path, body in files)
        with Container(id="diff-pane", classes="modal-pane"):
            with Horizontal(id="diff-header"):
                yield Static("diff", id="diff-title")
                yield Static(
                    Text.assemble(
                        (f"+{total_additions}", "bold #8fc49a"),
                        ("  ", "#777777"),
                        (f"−{total_deletions}", "bold #df8b91"),
                    ),
                    id="diff-total-stats",
                )
                yield Static(f"1 of {len(files)} files", id="diff-file-counter")
                yield ModalCloseButton("esc  close", id="modal-close")
            with ModalScroll(id="diff-body", classes="modal-body"):
                if not files:
                    is_clean = diff_text.strip() in {"", "No local changes found."}
                    yield EmptyState(
                        "Working tree is clean" if is_clean else "Diff unavailable",
                        diff_text.strip() or "There are no uncommitted changes to review.",
                    )
                for path, body in files:
                    card = DiffFileCard(path, body)
                    self._files.append(card)
                    yield card
            yield Static(
                "↑↓ scroll   n next file   p previous file   enter collapse   esc close",
                id="diff-hint",
                classes="modal-footer",
            )

    def _update_counter(self) -> None:
        if self._files:
            self.query_one("#diff-file-counter", Static).update(
                f"{self._file_index + 1} of {len(self._files)} files"
            )

    def action_next_file(self) -> None:
        if not self._files:
            return
        self._file_index = min(self._file_index + 1, len(self._files) - 1)
        self._files[self._file_index].scroll_visible()
        self._update_counter()

    def action_previous_file(self) -> None:
        if not self._files:
            return
        self._file_index = max(self._file_index - 1, 0)
        self._files[self._file_index].scroll_visible()
        self._update_counter()

    def action_toggle_collapse(self) -> None:
        if self._files:
            self._files[self._file_index].toggle_class("collapsed")
