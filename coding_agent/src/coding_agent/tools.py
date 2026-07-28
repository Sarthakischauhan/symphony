"""Filesystem and shell tools scoped to a workspace root."""

from __future__ import annotations

import subprocess
from pathlib import Path


class WorkspaceTools:
    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

    def _resolve(self, path: str) -> Path:
        target = (self.workspace / path).resolve()
        if not target.is_relative_to(self.workspace):
            raise ValueError(f"Path escapes workspace: {path}")
        return target

    def read(self, path: str) -> str:
        """Read a UTF-8 text file relative to the workspace."""
        return self._resolve(path).read_text(encoding="utf-8")

    def write(self, path: str, content: str) -> str:
        """Write a UTF-8 text file relative to the workspace."""
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"wrote {path}"

    def bash(self, command: str) -> str:
        """Run a shell command inside the workspace and return combined output."""
        completed = subprocess.run(
            command,
            shell=True,
            cwd=self.workspace,
            capture_output=True,
            text=True,
            timeout=10,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        if completed.returncode != 0:
            return f"exit={completed.returncode}\n{output}".rstrip()
        return output.rstrip() or "(no output)"
