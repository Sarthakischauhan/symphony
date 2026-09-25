"""Decide whether the most recent session is an interrupted run worth continuing."""

from __future__ import annotations

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


def resume_note(summary: SessionSummary, checkpoint: Checkpoint) -> str:
    jobs = ", ".join(checkpoint.metadata.get("background_jobs") or []) or "none"
    goal = checkpoint.metadata.get("goal") or summary.first_message
    return (
        f"previous run was interrupted at {summary.updated_at}; background jobs {jobs} were lost; "
        f"continue toward the original task: {goal}"
    )
