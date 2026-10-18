"""Pre-launch choice when a newer symphony-code release is published."""

from __future__ import annotations

from rich.console import Group
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from coding_agent.tui.theme import RESUME_CSS, SYMPHONY_RICH_THEME


class UpdateApp(App[bool]):
    """Ask whether to install the newer published release."""

    CSS = RESUME_CSS + """
    #update-mark {
        color: #e1c16e;
        text-style: bold;
        margin-bottom: 1;
    }
    """
    BINDINGS = [
        Binding("escape", "decline", "Not now", show=False),
        Binding("ctrl+c", "decline", "quit", show=False),
        Binding("left", "focus_previous", show=False),
        Binding("right", "focus_next", show=False),
    ]

    def __init__(self, current: str, latest: str) -> None:
        super().__init__()
        self.current = current
        self.latest = latest

    def compose(self) -> ComposeResult:
        with Container(id="resume-page"):
            yield Static("A NEW VERSION IS READY", id="update-mark")
            yield Static("Symphony found a newer release", id="resume-title")
            yield Static(
                f"Installed {self.current}   ·   Latest {self.latest}",
                id="resume-subtitle",
            )
            yield OptionList(
                Option(Group(
                    Text("›  Update now", no_wrap=True),
                    Text("   Install the latest symphony-code and restart", style="#737373"),
                ), id="yes"),
                Option(Group(
                    Text("›  Not now", no_wrap=True),
                    Text("   Keep this version and open Symphony", style="#737373"),
                ), id="no"),
                id="resume-list",
            )
            yield Static("↑↓ select   Enter confirm   Esc not now", id="resume-hint")

    def on_mount(self) -> None:
        self.console.push_theme(SYMPHONY_RICH_THEME, inherit=True)
        self.query_one("#resume-list", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.exit(event.option_id == "yes")

    def action_decline(self) -> None:
        self.exit(False)


def ask_to_update(current: str, latest: str) -> bool:
    """Show the update screen. False keeps the installed version."""
    return bool(UpdateApp(current, latest).run())
