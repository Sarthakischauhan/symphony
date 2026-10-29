"""The transcript row for a stored artifact: ``Artifact: <title>``, opened on click."""

from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import Any

from rich.text import Text
from textual.widgets import Static

from coding_agent.tui.theme import SYMPHONY_COLORS


def display_path(path: Path) -> str:
    """The entry path with the home folder as ``~``."""
    home = Path.home()
    return f"~/{path.relative_to(home)}" if path.is_relative_to(home) else str(path)


class ArtifactRow(Static):
    """Shows the title, kind and version, and below them the entry path the user can open.

    A click opens the entry with the system's default application.
    """

    def __init__(self, title: str, detail: str, path: Path) -> None:
        self.title = title
        self.path = path
        text = Text("  Artifact: ", style=SYMPHONY_COLORS["muted"])
        text.append(title, style=f"bold {SYMPHONY_COLORS['foreground']}")
        text.append(f"  {detail}\n", style=SYMPHONY_COLORS["muted"])
        text.append(f"    {display_path(path)}", style=f"underline {SYMPHONY_COLORS['muted_dim']}")
        super().__init__(text, classes="artifact")
        self.tooltip = f"Open {path}"

    def on_click(self, event: Any) -> None:
        webbrowser.open(self.path.as_uri())
        event.stop()

    def archive_text(self) -> str:
        return f"Artifact: {self.title} ({self.path})"
