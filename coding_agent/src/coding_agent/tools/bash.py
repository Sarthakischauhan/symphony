"""Run a shell command inside the workspace without blocking the event loop."""

from __future__ import annotations

import asyncio
import os
import signal

from pydantic import Field

from coding_agent.config import BashConfig
from coding_agent.tools.base import ToolArgsModel, WorkspaceTool

DEFAULT_BASH_CONFIG = BashConfig()


class BashArgs(ToolArgsModel):
    command: str = Field(
        ...,
        min_length=1,
        description=(
            "Shell command to run with cwd set to the working directory "
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
        "Run a shell command in the working directory and return combined "
        "stdout/stderr. Use for builds, tests, git, package managers, and other CLI work. "
        "Non-zero exits are returned as text (prefixed with exit=N), not as a tool failure. "
        "Timeouts include captured output. Output is capped to the last bytes. "
        "Child processes are killed as a group according to the configured limits."
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
            output, truncated, timed_out = await stream_output(
                proc,
                timeout,
                max_output_bytes=self.config.max_output_bytes,
            )
        except asyncio.CancelledError:
            await stop_process_group(proc)
            raise

        text = decode_capped(output, truncated, self.config.max_output_bytes)
        if timed_out:
            prefix = f"timed out after {timeout}s"
            return f"{prefix}\n{text}".rstrip() if text else prefix
        if proc.returncode not in (0, None):
            return f"exit={proc.returncode}\n{text}".rstrip() if text else f"exit={proc.returncode}"
        return text or "(no output)"


def decode_capped(output: bytes, truncated: bool, cap: int) -> str:
    if truncated:
        index = 0
        while index < len(output) and output[index] & 0xC0 == 0x80:
            index += 1
        output = output[index:]
    text = output.decode("utf-8", errors="replace").rstrip()
    if not truncated:
        return text
    notice = f"...[earlier output truncated, showing last {cap} bytes]..."
    return f"{notice}\n{text}" if text else notice


async def stream_output(
    proc: asyncio.subprocess.Process,
    timeout: float,
    *,
    max_output_bytes: int,
) -> tuple[bytes, bool, bool]:
    if proc.stdout is None:
        return b"", False, False

    buf = bytearray()
    truncated = False
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout

    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            await stop_process_group(proc)
            return bytes(buf), truncated, True
        try:
            chunk = await asyncio.wait_for(proc.stdout.read(4096), timeout=remaining)
        except TimeoutError:
            await stop_process_group(proc)
            return bytes(buf), truncated, True
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > max_output_bytes:
            truncated = True
            del buf[:-max_output_bytes]

    remaining = deadline - loop.time()
    try:
        await asyncio.wait_for(proc.wait(), timeout=max(remaining, 0.01))
    except TimeoutError:
        await stop_process_group(proc)
        return bytes(buf), truncated, True
    return bytes(buf), truncated, False


async def stop_process_group(proc: asyncio.subprocess.Process) -> None:
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
