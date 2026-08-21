"""read_file tool timeline widget."""

from __future__ import annotations

from coding_agent.tui.widgets.tools.base import ToolCallWidget

class ReadFileWidget(ToolCallWidget):
    """Compact, path-oriented presentation for the read_file tool."""

    def _tool_title(self) -> tuple[str, str]:
        return ("Read", "└")

    def _summary(self) -> str:
        path = self.arguments.get("path")
        if not path:
            return self.raw_arguments
        offset = int(self.arguments.get("offset") or 1)
        limit = int(self.arguments.get("limit") or 0)
        window = ""
        if offset != 1 or limit:
            end = offset + limit - 1 if limit else "…"
            window = f"  lines {offset}–{end}"
        return f"{path}{window}"

    def _result_summary(self) -> str:
        if not self.result:
            return ""
        if self.result.startswith("error:"):
            return self.result
        count = len(self.result.splitlines())
        size = len(self.result.encode("utf-8"))
        return f"Read {count} lines ({size:,} bytes)"
