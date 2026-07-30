"""Write a text file in the workspace."""

from __future__ import annotations

from coding_agent.tools.base import WorkspaceTool


class WriteFileTool(WorkspaceTool):
    name = "write_file"
    description = (
        "Write a UTF-8 text file relative to the workspace. "
        "Creates parent directories as needed. Overwrites existing files. "
        "Returns a short confirmation string."
    )

    def run(self, path: str, content: str) -> str:
        """Write a UTF-8 text file relative to the workspace."""
        target = self.resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"wrote {path} ({len(content)} bytes)"
