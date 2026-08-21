"""Modal view for showing the current workspace diff."""

from __future__ import annotations

from pathlib import Path

from rich.syntax import Syntax
from rich.text import Text
from textual.containers import Container, Horizontal
from textual.widgets import Static

from coding_agent.tui.modal.base import ModalBase, ModalCloseButton, ModalScroll
from coding_agent.tui.modal.components import EmptyState
from coding_agent.tui.styles.diff import DIFF_MODAL_CSS
from coding_agent.tui.theme import SYMPHONY_CODE_THEME
from coding_agent.utils.diff import diff_stats, read_workspace_diff, split_diff


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
            yield ModalCloseButton("×", id="modal-close")
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
