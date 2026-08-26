"""Run a shell command inside the workspace without blocking the event loop."""

from __future__ import annotations

import asyncio
import os
import signal

from pydantic import Field

from coding_agent.config import BashConfig, DEFAULT_CODING_AGENT_CONFIG
from coding_agent.tools.base import ToolArgsModel, WorkspaceTool

DEFAULT_BASH_CONFIG = DEFAULT_CODING_AGENT_CONFIG.tools.bash


class BashArgs(ToolArgsModel):
    command: str = Field(
        ...,
        min_length=1,
        description=(
            "Shell command to run with cwd set to the workspace root "
            "(e.g. 'python -m pytest', 'ls -la')."
        ),
    )
    timeout: int = Field(
        default=DEFAULT_BASH_CONFIG.default_timeout_seconds,
        ge=1,
        description="Seconds to wait before killing the process group.",
    )


class BashTool(WorkspaceTool):
    name = "bash"
    description = (
        "Run a shell command inside the workspace directory and return combined "
        "stdout/stderr. Use for builds, tests, git, package managers, and other CLI work. "
        "Output is streamed and capped. Non-zero exits are returned as text "
        "(prefixed with exit=N). Commands time out and child processes are killed "
        "as a group according to the configured limits."
    )
    args_model = BashArgs

    def __init__(self, workspace: str, *, config: BashConfig = DEFAULT_BASH_CONFIG) -> None:
        self.config = config
        super().__init__(workspace)
        timeout_schema = self.parameters["properties"]["timeout"]
        timeout_schema["default"] = config.default_timeout_seconds
        timeout_schema["maximum"] = config.max_timeout_seconds

    def prepare_args(self, args: dict[str, object]) -> dict[str, object]:
        prepared = dict(args)
        prepared.setdefault("timeout", self.config.default_timeout_seconds)
        return prepared

    async def run(self, command: str, timeout: int) -> str:
        if not isinstance(command, str) or not command.strip():
            return "error: command must be a non-empty string"
        timeout = min(max(int(timeout), 1), self.config.max_timeout_seconds)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=self.workspace,
                start_new_session=True,
            )
        except OSError as exc:
            return f"error: failed to run command: {exc}"

        try:
            output, truncated, timed_out = await _stream_output(
                proc,
                timeout,
                max_output_bytes=self.config.max_output_bytes,
            )
        except asyncio.CancelledError:
            await _stop_process_group(proc)
            raise

        if timed_out:
            return f"error: command timed out after {timeout}s"

        text = output.decode("utf-8", errors="replace")
        if truncated:
            text += (
                f"\n...[output truncated at {self.config.max_output_bytes} bytes]..."
            )
        text = text.rstrip()
        if proc.returncode not in (0, None):
            return f"exit={proc.returncode}\n{text}".rstrip()
        return text or "(no output)"


async def _stream_output(
    proc: asyncio.subprocess.Process,
    timeout: float,
    *,
    max_output_bytes: int,
) -> tuple[bytes, bool, bool]:
    # any failed output should not make its way out
    if proc.stdout is None:
        return b"", False, False

    chunks: list[bytes] = []
    stored = 0
    truncated = False
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout

    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            await _stop_process_group(proc)
            return b"".join(chunks), truncated, True
        try:
            chunk = await asyncio.wait_for(proc.stdout.read(4096), timeout=remaining)
        except TimeoutError:
            await _stop_process_group(proc)
            return b"".join(chunks), truncated, True
        if not chunk:
            break
        if stored < max_output_bytes:
            take = min(len(chunk), max_output_bytes - stored)
            chunks.append(chunk[:take])
            stored += take
            if take < len(chunk):
                truncated = True
        else:
            truncated = True

    remaining = deadline - loop.time()
    try:
        await asyncio.wait_for(proc.wait(), timeout=max(remaining, 0.01))
    except TimeoutError:
        await _stop_process_group(proc)
        return b"".join(chunks), truncated, True
    return b"".join(chunks), truncated, False


async def _stop_process_group(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            break
        try:
            await asyncio.wait_for(proc.wait(), timeout=1.0)
            return
        except asyncio.TimeoutError:
            continue
