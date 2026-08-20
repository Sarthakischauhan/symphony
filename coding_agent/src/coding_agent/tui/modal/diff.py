"""Modal view for showing the current workspace diff."""

from __future__ import annotations

from pathlib import Path

from rich.console import Group
from rich.syntax import Syntax
from textual.containers import Container, VerticalScroll
from textual.widgets import Static

from coding_agent.tui.modal.base import ModalBase, ModalCloseButton
from coding_agent.tui.modal.components import EmptyState
from coding_agent.tui.styles.diff import DIFF_MODAL_CSS
from coding_agent.tui.theme import SYMPHONY_CODE_THEME
from coding_agent.utils.diff import read_workspace_diff, split_diff


class DiffFileCard(Static):
    """One changed file with a clear header, stats, and highlighted patch."""

    def __init__(self, path: str, body: str) -> None:
        super().__init__(
            Group(
                Syntax(
                    body,
                    "diff",
                    theme=SYMPHONY_CODE_THEME,  # type: ignore[arg-type]
                    line_numbers=False,
                    word_wrap=False,
                ),
            ),
            classes="content-card diff-file-card",
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
            yield ModalCloseButton("×", id="modal-close")
            with VerticalScroll(id="diff-body", classes="modal-body"):
                if not files:
                    yield EmptyState(
                        "Working tree is clean" if not diff_text.strip() else "Diff unavailable",
                        diff_text.strip() or "There are no uncommitted changes to review.",
                    )
                for path, body in files:
                    yield DiffFileCard(path, body)
            yield Static(
                "↑↓ scroll   ·   Esc close",
                id="diff-hint",
                classes="modal-footer",
            )
