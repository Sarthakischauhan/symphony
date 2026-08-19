"""Run a shell command inside the workspace without blocking the event loop."""

from __future__ import annotations

import asyncio
import os
import signal

from pydantic import Field

from coding_agent.tools.base import ToolArgsModel, WorkspaceTool

DEFAULT_TIMEOUT_SECONDS = 30
MAX_TIMEOUT_SECONDS = 120
MAX_OUTPUT_BYTES = 32_000


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
        default=DEFAULT_TIMEOUT_SECONDS,
        ge=1,
        le=MAX_TIMEOUT_SECONDS,
        description="Seconds to wait before killing the process group.",
    )


class BashTool(WorkspaceTool):
    name = "bash"
    description = (
        "Run a shell command inside the workspace directory and return combined "
        "stdout/stderr. Use for builds, tests, git, package managers, and other CLI work. "
        "Output is streamed and capped. Non-zero exits are returned as text "
        f"(prefixed with exit=N). Commands time out after {DEFAULT_TIMEOUT_SECONDS} seconds "
        f"(max {MAX_TIMEOUT_SECONDS}s) and child processes are killed as a group."
    )
    args_model = BashArgs

    async def run(self, command: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> str:
        if not isinstance(command, str) or not command.strip():
            return "error: command must be a non-empty string"
        timeout = min(max(int(timeout), 1), MAX_TIMEOUT_SECONDS)

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
            output, truncated, timed_out = await _stream_output(proc, timeout)
        except asyncio.CancelledError:
            await _stop_process_group(proc)
            raise

        if timed_out:
            return f"error: command timed out after {timeout}s"

        text = output.decode("utf-8", errors="replace")
        if truncated:
            text += f"\n...[output truncated at {MAX_OUTPUT_BYTES} bytes]..."
        text = text.rstrip()
        if proc.returncode not in (0, None):
            return f"exit={proc.returncode}\n{text}".rstrip()
        return text or "(no output)"


async def _stream_output(
    proc: asyncio.subprocess.Process,
    timeout: float,
) -> tuple[bytes, bool, bool]:
    assert proc.stdout is not None
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
        except asyncio.TimeoutError:
            await _stop_process_group(proc)
            return b"".join(chunks), truncated, True
        if not chunk:
            break
        if stored < MAX_OUTPUT_BYTES:
            take = min(len(chunk), MAX_OUTPUT_BYTES - stored)
            chunks.append(chunk[:take])
            stored += take
            if take < len(chunk):
                truncated = True
        else:
            truncated = True

    remaining = deadline - loop.time()
    try:
        await asyncio.wait_for(proc.wait(), timeout=max(remaining, 0.01))
    except asyncio.TimeoutError:
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
