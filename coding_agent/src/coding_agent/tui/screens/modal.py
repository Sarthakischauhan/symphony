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


def _numbered_text(content: str) -> Text:
    """Render plain text with a stable, compact line-number gutter.

    This deliberately uses only Rich/Textual primitives; a full diff library is
    unnecessary for displaying an existing document. ``difflib`` remains the
    right stdlib tool for comparing two versions, as used by the diff tool.
    """
    # ``splitlines`` handles LF, CRLF, and lone CR without leaving carriage
    # returns in the rendered source. It also preserves intentional blank lines
    # between lines; a completely empty document still has one visible row.
    lines = content.splitlines()
    if not lines:
        lines = [""]
    width = max(2, len(str(len(lines))))
    rendered = Text(no_wrap=True, overflow="crop")
    for number, line in enumerate(lines, start=1):
        rendered.append(f"{number:>{width}} │ ", style="#687e8b")
        rendered.append(line, style="#d0d0d0")
        if number != len(lines):
            rendered.append("\n")
    return rendered


class ContentModal(ModalBase[None]):
    """Modal used to inspect transcript content with a code-style gutter."""

    CSS = CONTENT_MODAL_CSS

    def __init__(self, content: str) -> None:
        super().__init__()
        self.content = content

    def compose(self):  # type: ignore[no-untyped-def]
        with Container(id="content-pane", classes="modal-pane"):
            yield ModalCloseButton("Esc", id="modal-close")
            yield Static("Text preview", id="content-title")
            with ModalScroll(id="content-body", classes="modal-body"):
                # Keep the raw node for integrations that inspect modal content;
                # the numbered node is the visible review surface.
                yield Static(self.content, id="content-text", markup=False)
                yield Static(_numbered_text(self.content), id="content-numbered", markup=False)
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
