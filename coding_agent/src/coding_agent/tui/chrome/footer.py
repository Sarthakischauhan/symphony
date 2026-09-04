"""Footer: bottom-right `N% context | model | esc cancel` in muted gray."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from rich.table import Table
from rich.text import Text

from coding_agent.tui.theme.colors import SYMPHONY_COLORS

if TYPE_CHECKING:
    from coding_agent.tui.runtime.state import RunMetrics, UiRunState

SEGMENT_SEPARATOR = "   |   "
IDLE_HINT = "esc cancel"
QUESTION_HINT = "↵ approve   ↑↓ choose   esc deny"


def footer_hint(*, question_pending: bool) -> str:
    """Keyboard hint shown as the footer's last segment."""
    return QUESTION_HINT if question_pending else IDLE_HINT


def context_percent(metrics: RunMetrics) -> Optional[int]:
    """Context-window utilisation as a whole percentage, or None when unknown."""
    utilization = metrics.utilization
    if utilization is None and metrics.context_limit:
        if metrics.context_left is not None:
            utilization = 1 - (metrics.context_left / metrics.context_limit)
        else:
            tokens = metrics.tokens_used or metrics.cumulative_tokens or metrics.total_tokens
            utilization = tokens / metrics.context_limit
    if utilization is None:
        return None
    return round(max(0.0, min(utilization, 1.0)) * 100)


def footer_segments(state: UiRunState, *, hint: str) -> tuple[str, ...]:
    """Ordered right-hand footer clusters: context, model, hint."""
    segments: list[str] = []
    percent = context_percent(state.metrics)
    if percent is not None:
        segments.append(f"{percent}% context")
    if state.model_id:
        segments.append(state.model_id)
    segments.append(hint)
    return tuple(segments)


def phase_label(state: UiRunState) -> str:
    """Quiet left-hand activity word; empty while idle so the footer stays clean."""
    if state.phase == "idle":
        return ""
    return "paused" if state.phase == "paused" else "working"


def render_footer(state: UiRunState, *, hint: str) -> Table:
    """Render the footer row beneath the composer."""
    separator = Text(SEGMENT_SEPARATOR, style=SYMPHONY_COLORS["edge"])
    right = Text(no_wrap=True)
    for index, segment in enumerate(footer_segments(state, hint=hint)):
        if index:
            right.append_text(separator)
        right.append(segment)

    footer = Table.grid(expand=True, padding=0)
    footer.add_column(ratio=1, overflow="ellipsis", no_wrap=True)
    footer.add_column(justify="right", no_wrap=True)
    footer.add_row(Text(phase_label(state), no_wrap=True), right)
    return footer
