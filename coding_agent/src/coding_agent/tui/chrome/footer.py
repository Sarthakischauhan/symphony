"""Footer with workspace, context utilisation, and the active keyboard hint."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from rich.table import Table
from rich.text import Text

from coding_agent.tui.theme import SYMPHONY_COLORS

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
    """Return the context label, meter, and keyboard hint in display order."""
    metrics = state.metrics
    percent = context_percent(metrics)
    label = f"{percent}% context" if percent is not None else "context unknown"
    return (label, _context_count(metrics), hint)


def _context_count(metrics: RunMetrics) -> str:
    tokens = metrics.tokens_used or metrics.total_tokens or metrics.cumulative_tokens
    if metrics.context_limit is not None:
        return f"{tokens:,}/{metrics.context_limit:,}"
    return f"{tokens:,}" if tokens else "—"


def context_bar(state: UiRunState, *, width: int = 18) -> Text:
    """Render a heavier left-to-right context meter followed by token counts.

    The meter deliberately sits between the context label and its count: the
    label is its anchor on the left, while the count anchors the right edge of
    this small cluster. Full block glyphs make the one-line meter read more
    clearly than the previous thin box-drawing line.
    """
    metrics = state.metrics
    percent = context_percent(metrics) or 0
    filled = round(max(0, min(percent, 100)) * width / 100)
    tokens = metrics.tokens_used or metrics.total_tokens or metrics.cumulative_tokens
    limit = metrics.context_limit
    count = f"{tokens:,}/{limit:,}" if limit is not None else f"{tokens:,}"
    result = Text()
    # Usage fills from left to right; the remaining capacity uses the lighter
    # muted theme tone so the meter stays visible without competing with the
    # accent-filled portion.
    result.append("█" * filled, style=SYMPHONY_COLORS["accent"])
    result.append("░" * (width - filled), style=SYMPHONY_COLORS["muted_dim"])
    result.append(f" {count}")
    return result


def phase_label(state: UiRunState) -> str:
    """Quiet left-hand activity word; empty while idle so the footer stays clean."""
    if state.phase == "idle":
        return ""
    return "paused" if state.phase == "paused" else "working"


def render_footer(state: UiRunState, *, hint: str, workspace: str = "") -> Table:
    """Render status, directory, and context on the left; hint on the right."""
    left = Text(phase_label(state), no_wrap=True)
    if left.plain:
        left.append(SEGMENT_SEPARATOR, style=SYMPHONY_COLORS["edge"])
    location = left
    if workspace:
        location.append(workspace, style=SYMPHONY_COLORS["muted"])
        left = Text(SEGMENT_SEPARATOR, style=SYMPHONY_COLORS["edge"], no_wrap=True)
    percent = context_percent(state.metrics)
    label = f"{percent}% context" if percent is not None else "context unknown"
    left.append(label, style=SYMPHONY_COLORS["foreground"])
    if percent is not None:
        left.append(SEGMENT_SEPARATOR, style=SYMPHONY_COLORS["edge"])
        left.append_text(context_bar(state))
    right = Text(f"   {hint}", no_wrap=True)
    footer = Table.grid(expand=True, padding=0)
    footer.add_column(ratio=1, overflow="ellipsis", no_wrap=True)
    if workspace:
        # Only the path may shrink; keep usage readable beside the key hint.
        footer.add_column(no_wrap=True)
    footer.add_column(justify="right", no_wrap=True)
    if workspace:
        footer.add_row(location, left, right)
    else:
        footer.add_row(left, right)
    return footer
