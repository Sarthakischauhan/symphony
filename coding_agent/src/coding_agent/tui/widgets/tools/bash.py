"""Bash tool timeline widget."""

from __future__ import annotations

from rich.console import Group
from textual.widgets import Static

from coding_agent.tui.widgets.tools.base import ToolCallWidget
from coding_agent.tui.widgets.tools.header import BashToolHeader
from coding_agent.utils.text import clip_text

class BashToolWidget(ToolCallWidget):
    """Bash-specific row with command and lifecycle status on one line."""

    def __init__(self, call_id: str, tool_name: str) -> None:
        self._bash_label = Static(classes="bash-tool-label")
        self._bash_command = Static(classes="bash-tool-command")
        self._bash_status = Static(classes="bash-tool-status")
        super().__init__(call_id, tool_name)
        self.add_class("bash-tool")
        self._body.add_class("bash-tool-body")

    def compose(self):  # type: ignore[no-untyped-def]
        with BashToolHeader(classes="bash-tool-header"):
            yield self._bash_label
            yield self._bash_command
            yield self._bash_status
        yield self._body

    def refresh_content(self) -> None:
        marker = {
            "preparing": "○",
            "running": "●",
            "done": "✓",
            "failed": "×",
        }.get(self.status, "○")
        self._bash_label.update(f"{self._disclosure_symbol()} {marker}  Bash")
        self._bash_command.update(clip_text(self._summary(), 180))
        self._bash_status.update(self.status)
        self.remove_class(
            "status-preparing", "status-running", "status-done", "status-failed"
        )
        self.add_class(f"status-{self.status}")
        self._body.update(Group(*self._body_rows()))
