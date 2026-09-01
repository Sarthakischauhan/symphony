"""Workspace diff modal screen."""

from __future__ import annotations

import subprocess
from pathlib import Path

from rich.syntax import Syntax
from rich.text import Text
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

    def __init__(self, workspace: Path) -> None:
        super().__init__()
        self.workspace = workspace

    def compose(self):  # type: ignore[no-untyped-def]
        diff_text = read_workspace_diff(self.workspace)
        files = split_diff(diff_text)
        with Container(id="diff-pane", classes="modal-pane"):
            yield ModalCloseButton("Esc", id="modal-close")
            with ModalScroll(id="diff-body", classes="modal-body"):
                if not files:
                    is_clean = diff_text.strip() in {"", "No local changes found."}
                    yield EmptyState(
                        "Working tree is clean" if is_clean else "Diff unavailable",
                        diff_text.strip() or "There are no uncommitted changes to review.",
                    )
                for path, body in files:
                    yield DiffFileCard(path, body)
            yield Static(
                "↑↓ scroll   ·   Esc close",
                id="diff-hint",
                classes="modal-footer",
            )
