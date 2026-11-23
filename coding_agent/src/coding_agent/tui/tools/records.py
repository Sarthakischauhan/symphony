"""What a folded tool row keeps so its details can be reopened.

A finished call becomes one row in an activity group, and its card is dropped
so a long session does not hold a widget tree per call. The row keeps a
``ToolCallRecord``: the arguments, result and completion fields as plain data.
Clicking the row rebuilds a throwaway card from the record and opens it in the
details modal, so a folded Update still shows its diff and a folded Bash its
command and output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from coding_agent.tools.summary import ToolSummary

if TYPE_CHECKING:
    from coding_agent.tui.tools.calls import ToolCallWidget


@dataclass(frozen=True, eq=False)
class ToolCallRecord:
    """Plain data for one finished call. Never holds a widget."""

    call_id: str
    tool_name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    raw_arguments: str = ""
    result: str = ""
    status: str = "done"
    summary: ToolSummary | None = None
    exit_code: int | None = None
    duration: float | None = None

    def widget(self, workspace: Path | None = None) -> ToolCallWidget:
        """An unmounted card in this call's final state, for the details modal."""
        from coding_agent.tui.tools.calls import make_tool_widget

        tool = make_tool_widget(self.call_id, self.tool_name, workspace=workspace)
        tool.restore(self)
        return tool


__all__ = ["ToolCallRecord"]
