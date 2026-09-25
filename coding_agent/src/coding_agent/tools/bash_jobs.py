"""Background bash jobs that wake the agent through the harness child inbox.

Each job is registered in ``harness.child_tasks`` as a ``ChildTask`` whose task
is the exit watcher, so the run loop emits ``waiting_for_children`` and sleeps
until it ends. On exit one bounded message lands in ``harness._child_results``
and is injected on the next turn; the model never has to poll.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from typing import Any

from core_ai.types import Message
from core_harness.addons.subagent.background import ChildTask

from coding_agent.tools.bash import decode_capped, stop_process_group

WAKE_TAIL_BYTES = 2048
# A distinct status keeps jobs out of the running-subagent concurrency count.
JOB_STATUS = "background"


def log_tail(path: Path, cap: int) -> str:
    with path.open("rb") as handle:
        size = handle.seek(0, 2)
        handle.seek(max(size - cap, 0))
        return decode_capped(handle.read(), size > cap, cap)


class BashJobs:
    """Registry of background processes, owned by ``CodingAgent``, bound to its harness."""

    def __init__(self, log_dir: Path, *, max_seconds: int) -> None:
        self.log_dir = log_dir
        self.max_seconds = max_seconds
        self.harness: Any = None
        self.procs: dict[str, asyncio.subprocess.Process] = {}
        self.logs: dict[str, Path] = {}

    def bind(self, harness: Any) -> None:
        self.harness = harness

    def running(self) -> dict[str, int]:
        """Live jobs as ``{job_id: pid}``; the pid is also the job's process-group id."""
        return {job_id: proc.pid for job_id, proc in self.procs.items() if proc.returncode is None}

    async def start(self, command: str, cwd: Path) -> str:
        if self.harness is None:
            return "error: background jobs need an agent harness"
        job_id = uuid.uuid4().hex[:8]
        self.log_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.log_dir / f"{job_id}.log"
        try:
            with log_path.open("wb") as log:
                proc = await asyncio.create_subprocess_shell(
                    command, stdin=asyncio.subprocess.DEVNULL, stdout=log,
                    stderr=asyncio.subprocess.STDOUT, cwd=cwd, start_new_session=True,
                )
        except OSError as exc:
            return f"error: failed to run command: {exc}"
        self.procs[job_id], self.logs[job_id] = proc, log_path
        record = ChildTask(job_id, self.harness.agent_id, str(self.harness.session_id or ""),
                           f"bash:{command[:80]}", status=JOB_STATUS)
        record.task = asyncio.create_task(self._watch(record, proc, log_path), name=f"bash-job:{job_id}")
        self.harness.child_tasks[job_id] = record
        await asyncio.sleep(0)  # enter the watcher so a cancel always reaches its cleanup
        return (f"started background job {job_id}\nlog: {log_path}\n"
                "You will get its exit status and output tail when it ends; do not poll.")

    def output(self, job_id: str, cap: int) -> str:
        if job_id not in self.procs:
            return f"error: unknown background job {job_id!r}"
        code = self.procs[job_id].returncode
        state = "running" if code is None else f"exit={code}"
        return f"job {job_id} {state}\n{log_tail(self.logs[job_id], cap)}".rstrip()

    async def stop(self, job_id: str) -> str:
        if job_id not in self.procs:
            return f"error: unknown background job {job_id!r}"
        await stop_process_group(self.procs[job_id])
        return f"stopped background job {job_id}"

    async def _watch(self, record: ChildTask, proc: asyncio.subprocess.Process, log_path: Path) -> None:
        started = time.monotonic()
        try:
            await asyncio.wait_for(proc.wait(), timeout=self.max_seconds)
            status = f"exit={proc.returncode}"
        except TimeoutError:
            await stop_process_group(proc)
            status = f"timed out (max_background_seconds={self.max_seconds})"
        except asyncio.CancelledError:
            await stop_process_group(proc)
            record.status = "cancelled"
            raise
        record.status = "completed"
        tail = log_tail(log_path, WAKE_TAIL_BYTES)
        self.harness._child_results.append(Message(role="user", content=(
            f"Background job {record.child_id} {status} after {time.monotonic() - started:.1f}s. "
            f"Last output:\n{tail}\nFull log: {log_path}"
        )))
