"""Managed child tasks, independent of the parent tool invocation or UI."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from core_ai.types import Message


@dataclass
class ChildTask:
    child_id: str
    parent_id: str
    session_id: str
    label: str
    status: str = "running"
    output_text: str = ""
    task: asyncio.Task[None] | None = None

    def snapshot(self) -> dict[str, str]:
        return {
            "child_id": self.child_id, "parent_id": self.parent_id,
            "session_id": self.session_id, "label": self.label,
            "status": self.status, "output_text": self.output_text,
        }


async def start_child(parent: Any, child: Any, prompt: Any, identity: Any) -> ChildTask:
    record = ChildTask(child.agent_id, parent.agent_id, child.session_id, identity.label)
    parent.child_tasks[record.child_id] = record
    await parent.announce_child(child, identity)

    async def run() -> None:
        try:
            result = await parent.run_child(child, prompt, identity=identity, announce=False)
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
            parent._child_results.append(Message(
                role="user",
                content=(f"Subagent {record.label} ({record.child_id}) {record.status}.\n"
                         f"{record.output_text}"),
            ))

    record.task = asyncio.create_task(run(), name=f"subagent:{record.child_id}")
    # Establish cancellation handling before exposing the task to callers.
    await asyncio.sleep(0)
    return record


async def wait_for_child_result(parent: Any, timeout: float | None) -> None:
    """Suspend the runtime until a child finishes or the deadline."""
    tasks = {record.task for record in parent.child_tasks.values()
             if record.task is not None and not record.task.done()}
    if not tasks or parent._child_results:
        return
    await asyncio.wait(tasks, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
