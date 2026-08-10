"""Modal view for markdown-rendered agent learnings."""

from __future__ import annotations

from pathlib import Path

from textual.containers import Container, VerticalScroll
from textual.widgets import Static

from coding_agent.learning import LearningStore
from coding_agent.tui.modal.base import ModalBase, ModalCloseButton
from coding_agent.tui.styles.learning import LEARNING_MODAL_CSS
from coding_agent.tui.theme import themed_markdown


class LearningModal(ModalBase[None]):
    """Fullscreen modal showing stored learnings as rendered Markdown."""

    CSS = LEARNING_MODAL_CSS

    def __init__(self, workspace: Path) -> None:
        super().__init__()
        self.workspace = workspace

    def compose(self):  # type: ignore[no-untyped-def]
        markdown = LearningStore(self.workspace).to_markdown()
        with Container(id="learning-pane"):
            yield ModalCloseButton("×", id="modal-close")
            yield Static("Agent learnings", id="learning-title")
            with VerticalScroll(id="learning-body"):
                yield Static(themed_markdown(markdown), id="learning-markdown")
            yield Static("Esc to close", id="learning-hint")
