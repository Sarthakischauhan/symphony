"""Thin modal host widgets shared by TUI screens."""

from __future__ import annotations

from typing import Generic, TypeVar

from rich.console import Group
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from coding_agent.tui.theme import CONTENT_MODAL_CSS

ResultT = TypeVar("ResultT")


class ModalCloseButton(Static, can_focus=True):
    """Small top-right close control shared by all modal screens."""

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.screen.dismiss(None)

    def on_key(self, event: events.Key) -> None:
        if event.key in {"enter", "space"}:
            event.stop()
            self.screen.dismiss(None)


class ModalScroll(VerticalScroll):
    """Scrollable modal body that always reserves Escape for closing."""

    BINDINGS = [
        Binding("escape", "close_modal", "Close", show=False, priority=True),
    ]

    def action_close_modal(self) -> None:
        self.screen.dismiss(None)

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            event.stop()
            self.screen.dismiss(None)
            return
        await super()._on_key(event)


class ModalBase(ModalScreen[ResultT], Generic[ResultT]):
    """Base modal with a consistent close button and Escape behavior."""

    BINDINGS = [
        Binding("escape", "close_modal", "Close", show=False, priority=True),
    ]

    def action_close_modal(self) -> None:
        self.dismiss(None)


class ContentModal(ModalBase[None]):
    """Modal used to inspect transcript content hidden behind a compact link."""

    CSS = CONTENT_MODAL_CSS

    def __init__(self, content: str) -> None:
        super().__init__()
        self.content = content

    def compose(self):  # type: ignore[no-untyped-def]
        with Container(id="content-pane", classes="modal-pane"):
            yield ModalCloseButton("Esc", id="modal-close")
            with ModalScroll(id="content-body", classes="modal-body"):
                yield Static(self.content, id="content-text", markup=False)
            yield Static("↑↓ scroll   ·   Esc close", classes="modal-footer")

# --- components.py ---
class EmptyState(Static):
    """Friendly empty state shared by data-backed modal screens."""

    def __init__(self, title: str, detail: str, **kwargs: object) -> None:
        super().__init__(
            Group(
                Text("◇", style="bold #738794"),
                Text(title, style="bold #c8c8c8"),
                Text(detail, style="#6f6f6f"),
            ),
            classes="empty-state",
            **kwargs,
        )
