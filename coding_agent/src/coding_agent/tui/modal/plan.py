"""Modal view for the latest agent plan."""

from __future__ import annotations

from pathlib import Path

from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from coding_agent.plan import PlanStore
from coding_agent.tui.styles.plan import PLAN_MODAL_CSS
from coding_agent.tui.theme import themed_markdown


class PlanModal(ModalScreen[None]):
    """Fullscreen modal showing the latest workspace plan."""

    CSS = PLAN_MODAL_CSS

    def __init__(self, workspace: Path) -> None:
        super().__init__()
        self.workspace = workspace

    def compose(self):  # type: ignore[no-untyped-def]
        markdown = PlanStore(self.workspace).to_markdown()
        with Container(id="plan-pane"):
            yield Static("Current plan", id="plan-title")
            with VerticalScroll(id="plan-body"):
                yield Static(themed_markdown(markdown), id="plan-markdown")
            yield Static("Esc to close", id="plan-hint")

    def on_key(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.key == "escape":
            self.dismiss(None)
