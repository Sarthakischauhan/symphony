"""Run a shell command inside the workspace."""

from __future__ import annotations

import subprocess

from pydantic import Field

from coding_agent.tools.base import ToolArgsModel, WorkspaceTool

DEFAULT_TIMEOUT_SECONDS = 30


class BashArgs(ToolArgsModel):
    command: str = Field(
        ...,
        min_length=1,
        description=(
            "Shell command to run with cwd set to the workspace root "
            "(e.g. 'python -m pytest', 'ls -la')."
        ),
    )


class BashTool(WorkspaceTool):
    name = "bash"
    description = (
        "Run a shell command inside the workspace directory and return combined "
        "stdout/stderr. Use for builds, tests, git, package managers, and other CLI work. "
        f"Non-zero exits are returned as text (prefixed with exit=N). "
        f"Commands time out after {DEFAULT_TIMEOUT_SECONDS} seconds."
    )
    args_model = BashArgs

    def run(self, command: str) -> str:
        if not isinstance(command, str) or not command.strip():
            return "error: command must be a non-empty string"

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
        except OSError as exc:
            return f"error: failed to run command: {exc}"

        output = (completed.stdout or "") + (completed.stderr or "")
        if completed.returncode != 0:
            return f"exit={completed.returncode}\n{output}".rstrip()
        return output.rstrip() or "(no output)"
