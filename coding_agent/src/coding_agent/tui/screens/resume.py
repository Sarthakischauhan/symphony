"""Pre-launch selector for a persisted conversation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from coding_agent.tui.theme import RESUME_CSS, SYMPHONY_RICH_THEME
from coding_agent.tui.transcript import clip_text


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


async def load_session_options(persistence: Any) -> list[SessionOption]:
    """Build display rows through the existing persistence interface."""
    options: list[SessionOption] = []
    for session in await persistence.list_sessions():
        messages = await persistence.load_conversation(session_id=session.session_id)
        first_message = next(
            (
                str(message.content).strip()
                for message in messages
                if message.role == "user" and message.content
            ),
            "Untitled conversation",
        )
        options.append(
            SessionOption(
                session.session_id,
                session.updated_at,
                first_message,
                len(messages),
            )
        )
    return options


def _row(session: SessionOption) -> Option:
    content = Text("› ")
    content.append(clip_text(session.first_message.replace("\n", " "), 116))
    content.append("\n  ")
    content.append(_relative_time(session.updated_at), style="#737373")
    content.append(f"   {session.message_count} messages", style="#737373")
    content.append(f"   {session.session_id}", style="#555555")
    return Option(content, id=session.session_id)


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

    def compose(self) -> ComposeResult:
        with Container(id="resume-page"):
            yield Static("Resume a previous session", id="resume-title")
            yield Static("Select a conversation to continue", id="resume-subtitle")
            yield OptionList(*(_row(session) for session in self.sessions), id="resume-list")
            yield Static("↑↓ select   Enter resume   Esc quit", id="resume-hint")

    def on_mount(self) -> None:
        self.console.push_theme(SYMPHONY_RICH_THEME, inherit=True)
        self.query_one("#resume-list", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.exit(event.option_id)

    def action_cancel(self) -> None:
        self.exit(None)
