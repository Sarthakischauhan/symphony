"""Formatting for the compact live TUI status line."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.table import Table
from rich.text import Text

from coding_agent.tui.state import UiRunState


def render_status(state: UiRunState, workspace: Path) -> Table:
    """Render the status line shown beneath the conversation transcript."""
    metrics = state.metrics
    phase = state.phase if state.phase in {"idle", "paused"} else "working"
    color = "#d7a84b" if phase == "working" else "#72a57a" if phase == "idle" else "#888888"
    line = Text("● ", style=color)
    line.append(phase, style="#858585")
    tokens = metrics.tokens_used or metrics.cumulative_tokens or metrics.total_tokens
    if tokens:
        line.append(
            f"   {tokens:,} context tokens",
            style="#5e5e5e",
        )
    utilization = metrics.utilization
    if utilization is None and metrics.context_limit and metrics.context_left is not None:
        utilization = 1 - (metrics.context_left / metrics.context_limit)
    if utilization is not None:
        line.append(f"   context {utilization:.0%}", style="#5e5e5e")
    line.append(f"   {workspace}", style="#4f4f4f")

    clock = Text(datetime.now().strftime("%d/%m   %H:%M:%S"), style="#555555")
    footer = Table.grid(expand=True, padding=0)
    footer.add_column(ratio=1, overflow="ellipsis", no_wrap=True)
    footer.add_column(justify="right", no_wrap=True)
    footer.add_row(line, clock)
    return footer
