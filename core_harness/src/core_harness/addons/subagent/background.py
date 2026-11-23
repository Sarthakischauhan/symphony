"""Managed child tasks, independent of the parent tool invocation or UI."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from core_ai.types import Message

STALL_SECONDS = 120.0
STALL_POLL_SECONDS = 5.0


@dataclass
class ChildTask:
    child_id: str
    parent_id: str
    session_id: str
    label: str
    status: str = "running"
    output_text: str = ""
    task: asyncio.Task[None] | None = None
    child: Any = None
    identity: Any = None
    messages: list[Message] = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float = 0.0
    current_tool: str = ""
    last_output_at: float = 0.0
    stalled: bool = False

    def snapshot(self) -> dict[str, Any]:
        return {
            "child_id": self.child_id, "parent_id": self.parent_id,
            "session_id": self.session_id, "label": self.label,
            "status": self.status, "output_text": self.output_text,
            "model_id": getattr(self.child, "model_id", ""),
            "elapsed_seconds": round((self.finished_at or time.monotonic()) - self.started_at, 1) if self.started_at else 0,
            "current_tool": self.current_tool, "stalled": self.stalled,
        }


async def start_child(parent: Any, child: Any, prompt: Any, identity: Any) -> ChildTask:
    record = ChildTask(child.agent_id, parent.agent_id, child.session_id, identity.label, child=child, identity=identity)
    parent.child_tasks[record.child_id] = record
    await parent.announce_child(child, identity)
    await continue_child(parent, record, prompt)
    return record


async def continue_child(parent: Any, record: ChildTask, prompt: Any) -> None:
    """Start another turn on a finished child, retaining its session."""
    if record.task is not None and not record.task.done():
        raise ValueError("child is still running")
    child, identity = record.child, record.identity
    record.status = "running"
    record.output_text = ""
    record.started_at = record.last_output_at = time.monotonic()
    record.finished_at = 0.0
    record.current_tool = ""
    record.stalled = False

    def observe(event_type: str, payload: dict[str, Any]) -> None:
        if payload.get("agent_id") != record.child_id:
            return
        if event_type == "tool_execution_started":
            record.current_tool = str(payload.get("tool_name") or "")
            record.last_output_at = time.monotonic()
            record.stalled = False
        elif event_type == "tool_execution_output":
            record.last_output_at = time.monotonic()
            record.stalled = False
        elif event_type in {"tool_execution_completed", "tool_execution_failed"}:
            record.current_tool = ""
            record.stalled = False

    unsubscribe = child.sink.subscribe(observe)

    async def watch() -> None:
        while True:
            await asyncio.sleep(STALL_POLL_SECONDS)
            if record.current_tool == "bash" and not record.stalled and time.monotonic() - record.last_output_at >= STALL_SECONDS:
                record.stalled = True
                notice = f"Subagent {record.label} ({record.child_id}) bash command has produced no output for {STALL_SECONDS:g} seconds."
                parent._child_results.append(Message(role="user", content=notice))
                parent._child_result_ready.set()
                await parent.emit("child_progress", {"child_id": record.child_id, "message": notice, **record.snapshot()})

    async def run() -> None:
        watcher = asyncio.create_task(watch())
        try:
            result = await parent.run_child(child, prompt, identity=identity, announce=False,
                                            conversation=record.messages or None)
            record.messages = result.messages
            record.output_text = result.output_text
            record.status = child._last_run_status
        except asyncio.CancelledError:
            record.status = "cancelled"
            record.output_text = "Child cancelled"
            raise
        except Exception as exc:
            record.status = "failed"
            record.output_text = str(exc)
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
            unsubscribe()
            record.finished_at = time.monotonic()
            record.current_tool = ""
            parent._child_results.append(Message(
                role="user",
                content=(f"Subagent {record.label} ({record.child_id}) {record.status}.\n"
                         f"{record.output_text}"),
            ))
            parent._child_result_ready.set()

    record.task = asyncio.create_task(run(), name=f"subagent:{record.child_id}")
    await asyncio.sleep(0)


async def wait_for_child_result(parent: Any, timeout: float | None) -> None:
    """Suspend the runtime until a child finishes or the deadline."""
    tasks = {record.task for record in parent.child_tasks.values()
             if record.task is not None and not record.task.done()}
    if not tasks or parent._child_results:
        return
    waiter = asyncio.create_task(parent._child_result_ready.wait())
    try:
        await asyncio.wait(tasks | {waiter}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
    finally:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
