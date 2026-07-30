"""Run a shell command inside the workspace."""

from __future__ import annotations

import subprocess

from coding_agent.tools.base import WorkspaceTool

DEFAULT_TIMEOUT_SECONDS = 30


class BashTool(WorkspaceTool):
    name = "bash"
    description = (
        "Run a shell command inside the workspace directory and return combined "
        "stdout/stderr. Use for builds, tests, git, and other CLI work. "
        f"Commands time out after {DEFAULT_TIMEOUT_SECONDS} seconds."
    )

    def run(self, command: str) -> str:
        """Run a shell command inside the workspace and return combined output."""
        try:
            completed = subprocess.run(
                command,
                shell=True,
                cwd=self.workspace,
                capture_output=True,
                text=True,
                timeout=DEFAULT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return f"error: command timed out after {DEFAULT_TIMEOUT_SECONDS}s"

        output = (completed.stdout or "") + (completed.stderr or "")
        if completed.returncode != 0:
            return f"exit={completed.returncode}\n{output}".rstrip()
        return output.rstrip() or "(no output)"
