"""Modal view for structured agent learnings."""

from __future__ import annotations

from pathlib import Path

from textual.containers import Container, VerticalScroll
from textual.widgets import Static

from coding_agent.learning import LearningStore
from coding_agent.tui.modal.base import ModalBase, ModalCloseButton
from coding_agent.tui.modal.components import EmptyState, LearningCard, ModalHeader
from coding_agent.tui.styles.learning import LEARNING_MODAL_CSS


class LearningModal(ModalBase[None]):
    """Fullscreen modal showing stored learnings as scannable cards."""

    CSS = LEARNING_MODAL_CSS

    def __init__(self, workspace: Path) -> None:
        super().__init__()
        self.workspace = workspace

    def compose(self):  # type: ignore[no-untyped-def]
        lessons = list(reversed(LearningStore(self.workspace).load()))
        with Container(id="learning-pane", classes="modal-pane"):
            yield ModalCloseButton("×", id="modal-close")
            yield ModalHeader(
                "Workspace memory",
                "Agent learnings",
                "Patterns retained from completed work",
                id="learning-title",
            )
            with VerticalScroll(id="learning-body", classes="modal-body"):
                if not lessons:
                    yield EmptyState(
                        "No learnings yet",
                        "Lessons from successful agent runs will collect here.",
                    )
                for index, lesson in enumerate(lessons, start=1):
                    yield LearningCard(lesson, index)
            yield Static(
                "↑↓ scroll   ·   Esc close",
                id="learning-hint",
                classes="modal-footer",
            )
