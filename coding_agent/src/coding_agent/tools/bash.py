"""Run a shell command inside the workspace without blocking the event loop."""

from __future__ import annotations

import asyncio
import codecs
import contextlib
import os
import signal
from types import TracebackType
from typing import TYPE_CHECKING, Literal, TypeAlias

from core_harness import EventSink
from core_harness.tools import current_tool_call_id
from pydantic import Field

from coding_agent.config import BashConfig
from coding_agent.tools.base import ToolArgsModel, WorkspaceTool

if TYPE_CHECKING:
    from coding_agent.tools.bash_jobs import BashJobs

DEFAULT_BASH_CONFIG = BashConfig()
# Live output for UIs (the TUI's running Bash card shows its tail). Chunks are
# coalesced so a chatty command costs at most one event per interval.
OUTPUT_EVENT = "tool_execution_output"
OUTPUT_FLUSH_SECONDS = 0.1
# Most characters sent per event. A UI shows a tail, so when a burst exceeds
# this only its newest lines are sent; the tool result is not affected.
OUTPUT_EVENT_CHARS = 4096
Stream: TypeAlias = Literal["stdout", "stderr"]


class CommandFailed(RuntimeError):
    """A command exited non-zero. The harness reports any raised error as ``status="error"``.

    The message keeps the ``exit=N`` line and the output the model reads; hosts take
    the exit code from :attr:`BashTool.exit_codes`, never from this text.
    """

    def __init__(self, exit_code: int, output: str) -> None:
        self.exit_code = exit_code
        super().__init__(f"exit={exit_code}\n{output}".rstrip() if output else f"exit={exit_code}")


class BashArgs(ToolArgsModel):
    command: str = Field(
        default="",
        description=(
            "Shell command to run with cwd set to the working directory. Pipelines, &&, loops, "
            "and heredoc scripts are fine (e.g. 'python -m pytest -q 2>&1 | tail -20', "
            "'rg -l foo | xargs wc -l'). Required for action=run."
        ),
    )
    timeout: int = Field(
        default=DEFAULT_BASH_CONFIG.default_timeout_seconds,
        ge=1,
        description="Seconds to wait before killing the process group.",
    )
    background: bool = Field(
        default=False,
        description=(
            "Run detached and return a job id plus log path at once (for long builds or "
            "test suites). When it exits you are sent its status and output tail "
            "automatically; do not poll. The run cannot finish while a job is alive."
        ),
    )
    action: Literal["run", "output", "stop"] = Field(
        default="run",
        description="run a command; output: tail a background job's log; stop: kill a background job.",
    )
    job_id: str = Field(default="", description="Background job id for action=output or stop.")


class BashTool(WorkspaceTool):
    name = "bash"
    description = (
        "Run a shell command (bash) in the working directory and return combined stdout/stderr. "
        "Reach for this early and often: one well-built command usually beats many small tool calls. "
        "Use pipelines and chaining (rg -n 'TODO' src | head -50, git log --oneline -20 && git status, "
        "ls -R | wc -l), loops, heredocs, and short inline scripts (python - <<'EOF' ... EOF) to explore, "
        "count, compare, transform, and verify in a single call. Prefer it for builds, tests, git, "
        "package managers, codebase surveys, and quick checks; keep read_file for reading a file you "
        "will edit and patch/write_file for edits. "
        "A non-zero exit is a tool error whose text starts with exit=N and includes the output. "
        "Timeouts include captured output. Output is capped to the last bytes, so filter or limit "
        "noisy output in the command itself. "
        "Child processes are killed as a group according to the configured limits."
    )
    args_model = BashArgs

    def __init__(
        self, workspace: str, *, config: BashConfig = DEFAULT_BASH_CONFIG, jobs: BashJobs | None = None
    ) -> None:
        self.config = config
        self.jobs = jobs
        # Exit status per finished foreground run, keyed by tool_call_id. Hosts
        # read (and pop) it when the call's tool_execution_completed arrives.
        self.exit_codes: dict[str, int] = {}
        super().__init__(workspace)
        timeout_schema = self.parameters["properties"]["timeout"]
        timeout_schema["default"] = config.default_timeout_seconds
        timeout_schema["maximum"] = config.max_timeout_seconds

    def prepare_args(self, args: dict[str, object]) -> dict[str, object]:
        prepared = super().prepare_args(args)
        prepared.setdefault("timeout", self.config.default_timeout_seconds)
        return prepared

    async def run(
        self,
        command: str,
        timeout: int,
        background: bool = False,
        action: str = "run",
        job_id: str = "",
        sink: EventSink | None = None,
    ) -> str:
        if background or action != "run":
            return await self.run_job(command, action, job_id)
        if not isinstance(command, str) or not command.strip():
            return "error: command must be a non-empty string"
        timeout = min(max(int(timeout), 1), self.config.max_timeout_seconds)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.workspace,
                start_new_session=True,
            )
        except OSError as exc:
            return f"error: failed to run command: {exc}"

        tool_call_id = current_tool_call_id.get()
        live = OutputStream(sink, tool_call_id) if sink is not None and tool_call_id else None
        try:
            async with contextlib.AsyncExitStack() as stack:
                if live is not None:
                    await stack.enter_async_context(live)
                output, truncated, timed_out = await stream_output(
                    proc,
                    timeout,
                    max_output_bytes=self.config.max_output_bytes,
                    live=live,
                )
        except asyncio.CancelledError:
            await stop_process_group(proc)
            raise

        text = decode_capped(output, truncated, self.config.max_output_bytes)
        if timed_out:
            prefix = f"timed out after {timeout}s"
            return f"{prefix}\n{text}".rstrip() if text else prefix
        if proc.returncode is not None and tool_call_id:
            self.exit_codes[tool_call_id] = proc.returncode
        if proc.returncode not in (0, None):
            raise CommandFailed(proc.returncode, text)
        return text or "(no output)"

    async def run_job(self, command: str, action: str, job_id: str) -> str:
        if self.jobs is None:
            return "error: background jobs are not available here"
        if action == "run":
            if not command.strip():
                return "error: command must be a non-empty string"
            return await self.jobs.start(command, self.workspace)
        if not job_id:
            return f"error: job_id is required for action={action}"
        if action == "output":
            return self.jobs.output(job_id, self.config.max_output_bytes)
        return await self.jobs.stop(job_id)


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


class OutputStream:
    """Send a running command's output to the sink as ``tool_execution_output``.

    ``feed`` only buffers; while the context is open a pump task emits the
    buffer every ``OUTPUT_FLUSH_SECONDS``, and leaving the context normally
    (exit or timeout) sends what is left. A cancelled command sends nothing
    more. Payload: ``tool_call_id``, ``tool_name``, the text ``delta`` and its
    ``stream`` (``stdout`` or ``stderr``); one event per run of same-stream text.
    """

    def __init__(self, sink: EventSink, tool_call_id: str) -> None:
        self.sink = sink
        self.tool_call_id = tool_call_id
        self.decoders: dict[Stream, codecs.IncrementalDecoder] = {
            "stdout": codecs.getincrementaldecoder("utf-8")(errors="replace"),
            "stderr": codecs.getincrementaldecoder("utf-8")(errors="replace"),
        }
        self.pending: list[tuple[Stream, str]] = []
        self.at_line_start = True
        self.pump: asyncio.Task[None] | None = None

    def feed(self, data: bytes, stream: Stream = "stdout") -> None:
        text = self.decoders[stream].decode(data)
        if not text:
            return
        if self.pending and self.pending[-1][0] == stream:
            self.pending[-1] = (stream, self.pending[-1][1] + text)
        else:
            self.pending.append((stream, text))

    async def flush(self) -> None:
        pending, self.pending = self.pending, []
        for stream, delta in pending:
            await self.send(stream, delta)

    async def send(self, stream: Stream, delta: str) -> None:
        if len(delta) > OUTPUT_EVENT_CHARS:
            # Keep the newest whole lines; restart the line the UI had open.
            start = len(delta) - OUTPUT_EVENT_CHARS
            newline = delta.find("\n", start)
            delta = delta[newline + 1 :] if 0 <= newline < len(delta) - 1 else delta[start:]
            if not self.at_line_start:
                delta = "\n" + delta
        if not delta:
            return
        self.at_line_start = delta.endswith("\n")
        await self.sink.emit(
            OUTPUT_EVENT,
            {"tool_call_id": self.tool_call_id, "tool_name": BashTool.name, "delta": delta, "stream": stream},
        )

    async def run_pump(self) -> None:
        while True:
            await asyncio.sleep(OUTPUT_FLUSH_SECONDS)
            await self.flush()

    async def __aenter__(self) -> OutputStream:
        self.pump = asyncio.create_task(self.run_pump())
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.pump is not None:
            self.pump.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.pump
        if exc_type is None:
            for stream, decoder in self.decoders.items():
                tail = decoder.decode(b"", final=True)
                if tail:
                    self.pending.append((stream, tail))
            await self.flush()


async def stream_output(
    proc: asyncio.subprocess.Process,
    timeout: float,
    *,
    max_output_bytes: int,
    live: OutputStream | None = None,
) -> tuple[bytes, bool, bool]:
    """Read stdout and stderr as they arrive into one buffer, in arrival order."""
    pipes: tuple[tuple[Stream, asyncio.StreamReader | None], ...] = (("stdout", proc.stdout), ("stderr", proc.stderr))
    readers = [(name, reader) for name, reader in pipes if reader is not None]
    if not readers:
        return b"", False, False

    buf = bytearray()
    truncated = False
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    reads: dict[asyncio.Task[bytes], Stream] = {}
    sources = dict(readers)

    def read(stream: Stream) -> None:
        reads[asyncio.ensure_future(sources[stream].read(4096))] = stream

    for name, _reader in readers:
        read(name)
    try:
        while reads:
            remaining = deadline - loop.time()
            if remaining <= 0:
                await stop_process_group(proc)
                return bytes(buf), truncated, True
            done, _pending = await asyncio.wait(reads, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                await stop_process_group(proc)
                return bytes(buf), truncated, True
            for task in done:
                stream = reads.pop(task)
                chunk = task.result()
                if not chunk:
                    continue
                if live is not None:
                    live.feed(chunk, stream)
                buf.extend(chunk)
                if len(buf) > max_output_bytes:
                    truncated = True
                    del buf[:-max_output_bytes]
                read(stream)
    finally:
        for task in reads:
            task.cancel()

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
