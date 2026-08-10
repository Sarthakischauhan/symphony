"""Shared behavior for Symphony modal screens."""

from __future__ import annotations

from typing import Generic, TypeVar

from textual import events
from textual.screen import ModalScreen
from textual.widgets import Static


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


class ModalBase(ModalScreen[ResultT], Generic[ResultT]):
    """Base modal with a consistent close button and Escape behavior."""

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            event.stop()
            self.dismiss(None)
