"""Read a text file from the workspace."""

from __future__ import annotations

from coding_agent.tools.base import WorkspaceTool


class ReadFileTool(WorkspaceTool):
    name = "read_file"
    description = (
        "Read a UTF-8 text file relative to the workspace. "
        "Returns the full file contents."
    )

    def run(self, path: str) -> str:
        """Read a UTF-8 text file relative to the workspace."""
        target = self.resolve_path(path)
        if not target.exists():
            return f"error: file not found: {path}"
        if not target.is_file():
            return f"error: not a file: {path}"
        try:
            return target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return f"error: file is not valid UTF-8 text: {path}"
