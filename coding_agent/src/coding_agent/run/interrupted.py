"""Decide whether the most recent session is an interrupted run worth continuing."""

from __future__ import annotations

import os
import signal
from typing import Optional

from core_harness import Checkpoint

from coding_agent.persistence import JsonlPersistence, SessionSummary


async def interrupted_session(persistence: JsonlPersistence) -> Optional[tuple[SessionSummary, Checkpoint]]:
    """Most recent session, only if its last checkpoint still says ``running``."""
    sessions = await persistence.list_sessions()
    if not sessions:
        return None
    checkpoint = await persistence.load_checkpoint(session_id=sessions[0].session_id)
    if checkpoint is None or checkpoint.status != "running":
        return None
    return sessions[0], checkpoint


def stop_orphaned_jobs(jobs: object) -> list[str]:
    """SIGKILL job process groups (own session, so pgid == pid) that outlived the killed run."""
    stopped = []
    for job_id, pid in (jobs.items() if isinstance(jobs, dict) else []):
        if not isinstance(pid, int) or pid <= 1:
            continue
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            continue
        stopped.append(f"{job_id} (pid {pid})")
    return stopped


def resume_note(summary: SessionSummary, checkpoint: Checkpoint, stopped: list[str]) -> str:
    goal = checkpoint.metadata.get("goal") or summary.first_message
    return (
        f"previous run was interrupted at {summary.updated_at}; "
        f"background jobs {', '.join(stopped) or 'none'} were stopped; "
        f"continue toward the original task: {goal}"
    )
