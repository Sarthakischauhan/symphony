"""Transient composer overlay for session updates and interrupt confirmations."""

from __future__ import annotations

from typing import Optional

from rich.console import Group
from rich.text import Text
from textual.widgets import Static

from coding_agent.tui.theme import SYMPHONY_COLORS

DEFAULT_HINT = "Press ctrl+q to quit the app"


class ComposerOverlay(Static):
    """A short-lived banner above the composer, matching the interrupt card."""

    def __init__(self) -> None:
        super().__init__(id="composer-overlay")
        self.title = ""
        self.hint = DEFAULT_HINT
        self._hide_timer: Optional[object] = None
        self.display = False

    def show(self, title: str, hint: str = DEFAULT_HINT, *, seconds: float = 3.2) -> None:
        """Replace the current overlay contents and restart the hide timer."""
        self.title = title
        self.hint = hint
        body = Group(
            Text(title, style=f"bold {SYMPHONY_COLORS['string']}"),
            Text.from_markup(self._hint_markup(hint), style=SYMPHONY_COLORS["foreground"]),
        )
        self.update(body)
        self.display = True
        if self._hide_timer is not None:
            self._hide_timer.stop()
        self._hide_timer = self.set_timer(seconds, self.hide)

    def hide(self) -> None:
        self.display = False
        self.title = ""
        self.hint = DEFAULT_HINT
        if self._hide_timer is not None:
            self._hide_timer.stop()
            self._hide_timer = None

    @staticmethod
    def _hint_markup(hint: str) -> str:
        """Emphasize the first ctrl+key chord in the hint line."""
        lowered = hint.lower()
        marker = "ctrl+"
        index = lowered.find(marker)
        if index < 0:
            return hint
        end = index + len(marker)
        while end < len(hint) and hint[end].isalnum():
            end += 1
        return f"{hint[:index]}[b]{hint[index:end]}[/b]{hint[end:]}"
