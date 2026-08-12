"""Modal view for asking the user a clarifying question."""

from __future__ import annotations

from textual import events
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Input, Static

from coding_agent.tui.modal.base import ModalBase, ModalCloseButton
from coding_agent.tui.styles.modal import MODAL_BASE_CSS


QUESTION_MODAL_CSS = MODAL_BASE_CSS + """
QuestionModal {
    align: center middle;
    background: rgba(0, 0, 0, 0.7);
}

#plan-pane {
    width: 80%;
    max-width: 100;
    padding: 1 2;
    background: #1b1b1b;
    border-left: solid #454545;
}

#plan-title {
    height: 1;
    color: #d0d0d0;
    padding-bottom: 1;
}

#plan-body {
    width: 100%;
    height: auto;
    padding-bottom: 1;
}

#question-text,
#question-choices {
    width: 100%;
    color: #d0d0d0;
}

#question-choices {
    color: #9a9a9a;
}

#question-answer {
    width: 100%;
    margin-top: 1;
}

#plan-actions {
    width: 100%;
    height: 1;
    margin-top: 1;
    padding: 0 1;
    background: #202020;
}

#plan-hint,
#question-submit-hint {
    width: 1fr;
    height: 1;
    color: #767676;
}
"""


class QuestionModal(ModalBase[str | None]):
    CSS = QUESTION_MODAL_CSS

    def __init__(self, question: str, *, choices: list[str] | None = None, default: str = "") -> None:
        super().__init__()
        self.question = question
        self.choices = list(choices or [])
        self.default = default

    def compose(self):  # type: ignore[no-untyped-def]
        with Container(id="plan-pane"):
            yield ModalCloseButton("×", id="modal-close")
            yield Static("Clarifying question", id="plan-title")
            with Vertical(id="plan-body"):
                yield Static(self.question, id="question-text")
                if self.choices:
                    yield Static("Choices: " + " · ".join(self.choices), id="question-choices")
                yield Input(
                    value=self.default,
                    placeholder="Type your answer and press Enter",
                    id="question-answer",
                )
            with Horizontal(id="plan-actions"):
                yield Static("Esc", id="plan-hint")
                yield Static("Enter to submit", id="question-submit-hint")

    def on_mount(self) -> None:
        self.query_one("#question-answer", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.dismiss((event.value or "").strip() or None)

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            event.stop()
            self.dismiss(None)
