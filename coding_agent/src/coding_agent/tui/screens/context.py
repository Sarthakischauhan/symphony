"""Stored vs sent context inspector."""

from __future__ import annotations

from typing import Optional

from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.widgets import Static

from coding_agent.tui.screens.modal import EmptyState, ModalBase, ModalCloseButton, ModalScroll
from coding_agent.tui.theme import CONTEXT_MODAL_CSS
from core_harness.context import ContextMessage, ContextReport

_ROLE_COLORS = {
    "system": "#738794",
    "user": "#8eafc2",
    "assistant": "#c7b66e",
    "tool": "#79a985",
}

_ROLE_SHORT = {
    "system": "SYS",
    "user": "MSG",
    "assistant": "AST",
    "tool": "TOOL",
}


def _token_label(value: int) -> str:
    if value >= 10_000:
        return f"{value / 1000:.1f}k"
    return f"{value:,}"


def _meter_bar(fraction: float, width: int = 22) -> str:
    clamped = max(0.0, min(1.0, fraction))
    filled = int(round(clamped * width))
    return "█" * filled + "░" * (width - filled)


class ContextBucketChip(Static, can_focus=True):
    """Clickable role filter for the context breakdown."""

    def __init__(self, role: str, caption: str, *, active: bool = False) -> None:
        self.role = role
        classes = "context-chip context-chip-active" if active else "context-chip"
        super().__init__(caption, classes=classes)

    def on_click(self, event: events.Click) -> None:
        event.stop()
        screen = self.screen
        if isinstance(screen, ContextModal):
            screen.set_filter(self.role)

    def on_key(self, event: events.Key) -> None:
        if event.key in {"enter", "space"}:
            event.stop()
            screen = self.screen
            if isinstance(screen, ContextModal):
                screen.set_filter(self.role)


class ContextModal(ModalBase[None]):
    """Small interactive breakdown of stored vs sent context."""

    CSS = CONTEXT_MODAL_CSS
    BINDINGS = [
        Binding("escape", "close_modal", "Close", show=False, priority=True),
        Binding("left", "prev_filter", "Previous", show=False),
        Binding("right", "next_filter", "Next", show=False),
    ]

    def __init__(self, report: ContextReport) -> None:
        super().__init__()
        self.report = report
        self._filter: Optional[str] = None
        self._filters: tuple[str, ...] = ("all",) + tuple(
            bucket.role for bucket in report.buckets if bucket.count
        )

    def compose(self):  # type: ignore[no-untyped-def]
        with Container(id="context-pane", classes="modal-pane"):
            with Horizontal(id="context-header"):
                yield Static("Context", id="context-title")
                yield ModalCloseButton("Esc", id="modal-close")
            yield Static(self._render_meters(), id="context-meters")
            with Horizontal(id="context-buckets"):
                for role, caption in self._chip_captions():
                    yield ContextBucketChip(role, caption, active=role == "all")
            yield Static(self._render_meta(), id="context-meta")
            with ModalScroll(id="context-body", classes="modal-body"):
                if not self.report.messages:
                    yield EmptyState(
                        "No conversation yet",
                        "Send a prompt first. /context then splits messages vs tool results.",
                    )
                else:
                    yield Static(self._render_rows(), id="context-list", markup=False)
            yield Static(
                "← → switch view   ·   click to filter",
                id="context-hint",
                classes="modal-footer",
            )

    def set_filter(self, role: str) -> None:
        self._filter = None if role in {"", "all"} else role
        self._refresh()

    def action_prev_filter(self) -> None:
        self._nudge_filter(-1)

    def action_next_filter(self) -> None:
        self._nudge_filter(1)

    def _nudge_filter(self, step: int) -> None:
        current = self._filter or "all"
        if current not in self._filters:
            current = "all"
        index = self._filters.index(current)
        self.set_filter(self._filters[(index + step) % len(self._filters)])

    def _chip_captions(self) -> list[tuple[str, str]]:
        chips = [("all", f"All  {_token_label(self.report.stored_tokens)}")]
        for bucket in self.report.buckets:
            if not bucket.count:
                continue
            chips.append(
                (bucket.role, f"{bucket.label}  {_token_label(bucket.tokens)}")
            )
        return chips

    def _render_meters(self) -> Text:
        stored = self.report.stored_tokens
        sent = self.report.sent_tokens
        limit = self.report.context_limit
        stored_frac = stored / limit if limit else 0.0
        sent_frac = sent / limit if limit else (sent / stored if stored else 0.0)
        text = Text()
        text.append("stored  ", style="#686868")
        text.append(f"{stored:,}", style="bold #d0d0d0")
        text.append(" tok   ", style="#686868")
        text.append(_meter_bar(stored_frac), style="#8eafc2")
        if limit:
            text.append(f"  {min(stored_frac * 100, 100):.0f}% of {limit:,}", style="#686868")
        text.append("\nsent    ", style="#686868")
        text.append(f"{sent:,}", style="bold #79a985")
        text.append(" tok   ", style="#686868")
        text.append(_meter_bar(sent_frac), style="#79a985")
        if limit:
            text.append(f"  {min(sent_frac * 100, 100):.0f}% of {limit:,}", style="#686868")
        saved = max(stored - sent, 0)
        if saved:
            text.append(f"\npruned  {saved:,} tok held back from the next model call", style="#686868")
        return text

    def _render_meta(self) -> str:
        active = "all messages" if self._filter is None else f"{self._filter} only"
        return (
            f"{self.report.message_count} messages  ·  "
            f"{self.report.tool_result_count} tool results  ·  "
            f"{self.report.stubbed_result_count} stubbed on send  ·  {active}"
        )

    def _visible_messages(self) -> tuple[ContextMessage, ...]:
        if self._filter is None:
            return self.report.messages
        return tuple(item for item in self.report.messages if item.role == self._filter)

    def _render_rows(self) -> Text:
        rows = Text()
        visible = self._visible_messages()
        if not visible:
            rows.append("Nothing in this bucket.", style="#686868")
            return rows
        rows.append("TYPE  TOKENS    SENT  STATE   CONTENT\n", style="#555555")
        for item in visible:
            color = _ROLE_COLORS.get(item.role, "#bdbdbd")
            short = _ROLE_SHORT.get(item.role, item.role[:3].upper())
            rows.append(f"{short:<4} ", style=color)
            rows.append(f"{_token_label(item.tokens):>6}", style="#c8c8c8")
            if item.sent_tokens != item.tokens:
                rows.append(f" → {_token_label(item.sent_tokens):>5}", style="#79a985")
            else:
                rows.append("         ", style="#101010")
            if item.stubbed:
                rows.append("  stub", style="#c67b82")
            elif item.role == "tool":
                rows.append("  full", style="#686868")
            else:
                rows.append("      ", style="#101010")
            label = item.tool_name or item.preview
            if item.tool_name and item.preview:
                label = f"{item.tool_name} · {item.preview}"
            rows.append(f"  {label[:64]}", style="#8a8a8a")
            rows.append("\n")
        return rows

    def _refresh(self) -> None:
        self.query_one("#context-meta", Static).update(self._render_meta())
        listing = self.query("#context-list")
        if listing:
            listing.first().update(self._render_rows())
        current = self._filter or "all"
        for chip in self.query(ContextBucketChip):
            chip.set_class(chip.role == current, "context-chip-active")
