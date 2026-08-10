"""Modal view for showing the current workspace diff."""

from __future__ import annotations

from pathlib import Path

from rich.syntax import Syntax
from rich.text import Text
from textual.containers import Container, VerticalScroll
from textual.widgets import Label, Static

from coding_agent.tui.modal.base import ModalBase, ModalCloseButton
from coding_agent.tui.styles.diff import DIFF_MODAL_CSS
from coding_agent.tui.theme import SYMPHONY_CODE_THEME
from coding_agent.utils.diff import read_workspace_diff, split_diff


class DiffModal(ModalBase[None]):
    """Fullscreen modal for inspecting the current git diff."""

    CSS = DIFF_MODAL_CSS

    def __init__(self, workspace: Path) -> None:
        super().__init__()
        self.workspace = workspace

    def compose(self):  # type: ignore[no-untyped-def]
        diff_text = read_workspace_diff(self.workspace)
        files = split_diff(diff_text)
        with Container(id="diff-pane"):
            yield ModalCloseButton("×", id="modal-close")
            yield Static("PR / workspace diff", id="diff-title")
            with VerticalScroll(id="diff-body"):
                if not files:
                    yield Static(Text(diff_text, style="#a0a0a0"))
                for path, body in files:
                    yield Label(path, classes="diff-file-name")
                    yield Static(
                        Syntax(
                            body,
                            "diff",
                            theme=SYMPHONY_CODE_THEME,  # type: ignore[arg-type]
                            line_numbers=False,
                        ),
                        classes="diff-file-body",
                    )
            yield Static("Esc to close", id="diff-hint")
