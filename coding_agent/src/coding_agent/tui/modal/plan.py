"""Modal view for the latest agent plan."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from textual import events
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Static

from coding_agent.plan import PlanStore
from coding_agent.tui.modal.base import ModalBase, ModalCloseButton
from coding_agent.tui.styles.plan import PLAN_MODAL_CSS
from coding_agent.tui.theme import themed_markdown


PlanAction = Literal["build"]


class PlanBuildAction(Static, can_focus=True):
    """Compact text action used in the plan status bar."""

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.screen.dismiss("build")

    def on_key(self, event: events.Key) -> None:
        if event.key in {"enter", "space"}:
            event.stop()
            self.screen.dismiss("build")


class PlanModal(ModalBase[PlanAction | None]):
    """Fullscreen modal showing the latest workspace plan."""

    CSS = PLAN_MODAL_CSS

    def __init__(self, workspace: Path) -> None:
        super().__init__()
        self.workspace = workspace

    def compose(self):  # type: ignore[no-untyped-def]
        store = PlanStore(self.workspace)
        markdown = store.to_markdown()
        with Container(id="plan-pane"):
            yield ModalCloseButton("×", id="modal-close")
            yield Static(f"Plan ready · {store.path.name}", id="plan-title")
            with VerticalScroll(id="plan-body"):
                yield Static(themed_markdown(markdown), id="plan-markdown")
            with Horizontal(id="plan-actions"):
                yield Static("Esc", id="plan-hint")
                yield PlanBuildAction("Build now", id="plan-build")
