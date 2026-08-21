"""Patch diff tool timeline widget."""

from __future__ import annotations

from rich.console import Group
from rich.text import Text

from coding_agent.tui.widgets.tools.base import ToolCallWidget
from coding_agent.utils.diff import diff_stats, make_unified_diff
from coding_agent.utils.text import clip_text

class PatchDiffWidget(ToolCallWidget):
    """Unified diff presentation for the exact-text patch tool."""

    MAX_DIFF_LINES = 80

    def __init__(self, call_id: str, tool_name: str) -> None:
        super().__init__(call_id, tool_name)
        self.add_class("diff-tool")

    def _diff(self) -> list[str]:
        old = str(self.arguments.get("old_str") or "")
        new = str(self.arguments.get("new_str") or "")
        if not old and not new:
            return []
        path = str(self.arguments.get("path") or "file")
        return make_unified_diff(old, new, path)

    def _stats(self, diff: list[str]) -> tuple[int, int]:
        return diff_stats(diff)

    def refresh_content(self) -> None:
        marker = {
            "preparing": "○",
            "running": "●",
            "done": "✓",
            "failed": "×",
        }.get(self.status, "○")
        path = str(self.arguments.get("path") or "")
        diff = self._diff()
        additions, deletions = self._stats(diff)

        title = f"{marker}  Update"
        if path:
            title = f"{title} ({path})"
        if diff:
            title = f"{title}  +{additions} -{deletions}"
        if self.status in {"preparing", "running"}:
            title = f"{title}   {self.status}"
        self.title = title
        summary = path
        if diff:
            stats = f"+{additions} -{deletions}"
            summary = f"{summary}  {stats}" if summary else stats
        self._tool_label.update(
            f"{self._disclosure_symbol()} {marker}  Update"
        )
        self._tool_command.update(summary)
        self._tool_status.update(self.status)
        self.remove_class(
            "status-preparing", "status-running", "status-done", "status-failed"
        )
        self.add_class(f"status-{self.status}")
        rows: list[Any] = []

        visible = diff[: self.MAX_DIFF_LINES]
        for line in visible:
            if line.startswith("@@"):
                rows.append(Text(line, style="#6688a8"))
            elif line.startswith("+"):
                rows.append(Text(line, style="#8fc49a on #203026"))
            elif line.startswith("-"):
                rows.append(Text(line, style="#df8b91 on #352225"))
            else:
                rows.append(Text(line, style="#686868"))
        if len(diff) > self.MAX_DIFF_LINES:
            hidden = len(diff) - self.MAX_DIFF_LINES
            rows.append(Text(f"… {hidden} diff lines hidden", style="#555555"))

        if self.result:
            result_color = "#d66b73" if self.status == "failed" else "#626262"
            rows.append(Text(f"└  {clip_text(self.result, 260)}", style=result_color))
        self._body.update(Group(*rows))
