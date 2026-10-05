"""Footer with workspace, context utilisation, and the active keyboard hint."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from rich.console import Console, ConsoleOptions, Group, RenderResult
from rich.table import Table
from rich.text import Text
from textual.widgets import Static

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


@dataclass(frozen=True)
class ResponsiveFooter:
    """Rich renderable which preserves useful footer content as width changes."""

    state: UiRunState
    hint: str
    workspace: str = ""

    def __rich_console__(
        self,
        _console: Console,
        options: ConsoleOptions,
    ) -> RenderResult:
        yield self._table(max(options.max_width, 1))

    def _usage(self, *, meter: bool, count: bool) -> Text:
        percent = context_percent(self.state.metrics)
        label = f"{percent}% context" if percent is not None else "context unknown"
        usage = Text(label, style=SYMPHONY_COLORS["foreground"], no_wrap=True)
        if meter and percent is not None:
            usage.append(SEGMENT_SEPARATOR, style=SYMPHONY_COLORS["edge"])
            usage.append_text(context_bar(self.state))
        elif count and percent is not None:
            usage.append(" ")
            usage.append(_context_count(self.state.metrics))
        return usage

    def _table(self, width: int) -> Table:
        # The keyboard hint and context label are the two invariant pieces.
        # Add the count, meter, activity and path only when each fits without
        # forcing Rich to turn the invariant pieces into unreadable fragments.
        label = self._usage(meter=False, count=False)
        counted = self._usage(meter=False, count=True)
        metered = self._usage(meter=True, count=True)
        gap = 3
        available = max(width - len(self.hint) - gap, 1)
        usage = metered if len(metered.plain) <= available else counted
        if len(usage.plain) > available:
            usage = label

        prefix = Text(no_wrap=True)
        phase = phase_label(self.state)
        remaining = available - len(usage.plain) - len(SEGMENT_SEPARATOR)
        if phase and remaining >= len(phase):
            prefix.append(phase)
        if self.workspace and remaining >= 8:
            if prefix.plain:
                prefix.append(SEGMENT_SEPARATOR, style=SYMPHONY_COLORS["edge"])
            prefix.append(self.workspace, style=SYMPHONY_COLORS["muted"])

        table = Table.grid(expand=True, padding=0)
        if prefix.plain:
            table.add_column(ratio=1, overflow="ellipsis", no_wrap=True)
            table.add_column(no_wrap=True)
            table.add_column(no_wrap=True)
        else:
            table.add_column(ratio=1, overflow="ellipsis", no_wrap=True)
        table.add_column(justify="right", overflow="ellipsis", no_wrap=True)
        right = Text(f"{gap * ' '}{self.hint}", overflow="ellipsis", no_wrap=True)
        if prefix.plain:
            separator = Text(SEGMENT_SEPARATOR, style=SYMPHONY_COLORS["edge"])
            table.add_row(prefix, separator, usage, right)
        else:
            table.add_row(usage, right)
        return table


def render_footer(
    state: UiRunState,
    *,
    hint: str,
    workspace: str = "",
) -> ResponsiveFooter:
    """Render a footer that adapts its detail to the available terminal width."""
    return ResponsiveFooter(state=state, hint=hint, workspace=workspace)


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
