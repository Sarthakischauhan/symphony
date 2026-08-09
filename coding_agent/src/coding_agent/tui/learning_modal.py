"""Modal view for markdown-rendered agent learnings."""

from __future__ import annotations

from pathlib import Path

from rich.markdown import Markdown
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from coding_agent.learning import LearningStore
from coding_agent.tui.styles.learning import LEARNING_MODAL_CSS


class LearningModal(ModalScreen[None]):
    """Fullscreen modal showing stored learnings as rendered Markdown."""

    CSS = LEARNING_MODAL_CSS

    def __init__(self, workspace: Path) -> None:
        super().__init__()
        self.workspace = workspace

    def compose(self):  # type: ignore[no-untyped-def]
        markdown = LearningStore(self.workspace).to_markdown()
        with Container(id="learning-pane"):
            yield Static("Agent learnings", id="learning-title")
            with VerticalScroll(id="learning-body"):
                yield Static(Markdown(markdown), id="learning-markdown")
            yield Static("Esc to close", id="learning-hint")

    def on_key(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.key == "escape":
            self.dismiss(None)
