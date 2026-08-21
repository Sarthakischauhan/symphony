"""Prompt composer widget."""

from __future__ import annotations

from textual.containers import Container, Horizontal
from textual.widgets import Static

from coding_agent.tui.widgets.base import PromptInput

class Composer(Container):
    """Input surface with an always-visible interaction hint."""

    def compose(self):  # type: ignore[no-untyped-def]
        from coding_agent.tui.slash_menu import SlashMenu

        yield SlashMenu(id="approval-menu")
        yield PromptInput(
            placeholder="Ask Symphony to build, fix, or explain…",
            id="prompt",
            soft_wrap=True,
            show_line_numbers=False,
        )
        with Horizontal(id="composer-footer"):
            yield Static("BUILD · Tab mode", id="composer-mode")
            yield Static("Ctrl+↵ send   Enter line break   Esc cancel", id="composer-hint")
