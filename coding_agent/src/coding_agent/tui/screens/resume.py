"""Pre-launch selector for a persisted conversation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from rich.cells import cell_len
from rich.console import Group
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from coding_agent.addons.persistence.active import active_session_ids
from coding_agent.tui.theme import RESUME_CSS, SYMPHONY_RICH_THEME
from core_ai.content import text_from_content
from core_harness.context import COMPACTED_CONTEXT_MARK


@dataclass(frozen=True)
class SessionOption:
    session_id: str
    updated_at: str
    first_message: str
    message_count: int


def _relative_time(value: str) -> str:
    try:
        updated = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    seconds = max(0, int((datetime.now(timezone.utc) - updated).total_seconds()))
    if seconds < 60:
        return "just now"
    if seconds < 3_600:
        return f"{seconds // 60}m ago"
    if seconds < 86_400:
        return f"{seconds // 3_600}h ago"
    return f"{seconds // 86_400}d ago"


async def load_session_options(
    persistence: Any,
    *,
    closed_only: bool = True,
) -> list[SessionOption]:
    """Build display rows through the existing persistence interface.

    Active sessions are owned by a live Symphony process and listed under
    ``~/.symphony/active``. The resume picker hides them so a conversation is
    not opened twice. Pass ``closed_only=False`` to include them.
    """
    open_ids = active_session_ids() if closed_only else set()
    options: list[SessionOption] = []
    for session in await persistence.list_sessions():
        if session.session_id in open_ids:
            continue
        # JsonlPersistence computes these cheap row fields while scanning each
        # file. Avoid reparsing every transcript when opening the picker.
        if getattr(session, "message_count", 0) or getattr(session, "first_message", ""):
            first_message = getattr(session, "first_message", "") or "Untitled conversation"
            message_count = getattr(session, "message_count", 0)
        else:
            loader = getattr(persistence, "load_transcript", persistence.load_conversation)
            messages = await loader(session_id=session.session_id)
            first_message = next(
                (
                    text_from_content(message.content).strip()
                    for message in messages
                    if message.role == "user"
                    and message.content
                    and not text_from_content(message.content).startswith(COMPACTED_CONTEXT_MARK)
                ),
                "Untitled conversation",
            )
            message_count = len(messages)
        options.append(
            SessionOption(session.session_id, session.updated_at, first_message, message_count)
        )
    return options


def _fit(text: str, width: int) -> str:
    """Clip by terminal cells, reserving one cell for an ellipsis."""
    if width <= 0:
        return ""
    if cell_len(text) <= width:
        return text
    if width == 1:
        return "…"
    kept = text
    while kept and cell_len(kept) > width - 1:
        kept = kept[:-1]
    return f"{kept}…"


def _row(session: SessionOption, width: int) -> Option:
    """Title on line one and aligned metadata on line two.

    Both lines are pre-clipped. Textual otherwise wraps long titles while
    measuring every session, which makes a long resume list slow to open.
    """
    title_width = max(1, width - 3)
    meta_width = max(1, width - 3)
    title = _fit(session.first_message.replace("\n", " "), title_width)
    meta = _fit(
        f"{_relative_time(session.updated_at):<8}  {session.message_count:>6}  {session.session_id}",
        meta_width,
    )
    heading = Text(f"›  {title}", no_wrap=True, overflow="ellipsis")
    heading.highlight_words(["›"], style="bold #e1c16e")
    details = Text(f"   {meta}", no_wrap=True, overflow="ellipsis", style="#737373")
    return Option(Group(heading, details), id=session.session_id)


class ResumeApp(App[str | None]):
    """Choose a session before the conversation UI is created."""

    CSS = RESUME_CSS
    BINDINGS = [
        Binding("escape", "cancel", "quit"),
        Binding("ctrl+c", "cancel", "quit", show=False),
    ]

    def __init__(self, sessions: list[SessionOption]) -> None:
        super().__init__()
        self.sessions = sessions
        self._row_width = 0

    def compose(self) -> ComposeResult:
        with Container(id="resume-page"):
            yield Static("Resume a previous session", id="resume-title")
            yield Static("Select a conversation to continue", id="resume-subtitle")
            yield OptionList(id="resume-list")
            yield Static("↑↓ select   Enter resume   Esc quit", id="resume-hint")

    def on_resize(self, event: events.Resize) -> None:
        # Page padding is 2, row padding is 4, and the scrollbar takes 1.
        width = max(1, event.size.width - 7)
        if width == self._row_width:
            return
        self._row_width = width
        options = self.query_one("#resume-list", OptionList)
        highlighted = options.highlighted
        options.set_options(_row(session, width) for session in self.sessions)
        if self.sessions:
            options.highlighted = min(highlighted or 0, len(self.sessions) - 1)

    def on_mount(self) -> None:
        self.console.push_theme(SYMPHONY_RICH_THEME, inherit=True)
        self.query_one("#resume-list", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.exit(event.option_id)

    def action_cancel(self) -> None:
        self.exit(None)
