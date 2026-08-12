"""Formatting for the compact live TUI status line."""

from __future__ import annotations

from pathlib import Path

from rich.text import Text

from coding_agent.tui.state import UiRunState


def render_status(state: UiRunState, workspace: Path) -> Text:
    """Render the status line shown beneath the conversation transcript."""
    metrics = state.metrics
    phase = state.phase if state.phase in {"idle", "paused"} else "working"
    color = "#d7a84b" if phase == "working" else "#72a57a" if phase == "idle" else "#888888"
    line = Text("● ", style=color)
    line.append(phase, style="#858585")
    if metrics.tokens_used:
        line.append(
            f"   {metrics.tokens_used:,} context tokens",
            style="#5e5e5e",
        )
    if metrics.context_limit and metrics.context_left is not None:
        used = 1 - (metrics.context_left / metrics.context_limit)
        line.append(f"   context {used:.0%}", style="#5e5e5e")
    line.append(f"   {workspace}", style="#4f4f4f")
    return line
