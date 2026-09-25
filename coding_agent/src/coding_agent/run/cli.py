"""``symphony run --unattended [--detach] "<task>"`` and ``symphony --resume --continue``."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Optional, Sequence

from core_ai import has_configured_provider

from coding_agent.agent import build_agent
from coding_agent.config import ensure_spawn_settings
from coding_agent.credentials import load_provider_env
from coding_agent.persistence import JsonlPersistence, sessions_dir
from coding_agent.run.detach import detach
from coding_agent.run.interrupted import interrupted_session, resume_note, stop_orphaned_jobs
from coding_agent.run.log_sink import LogLineSink


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="symphony run", description="Run one task headless, with no human.")
    parser.add_argument("task", help="Task prompt")
    parser.add_argument(
        "--unattended", action="store_true", required=True,
        help="Required: auto-approve tools (approvals.deny still applies) and auto-answer ask_user",
    )
    parser.add_argument("--detach", action="store_true", help="Run in the background; print pid, log, session id")
    parser.add_argument("--model", default=None, help="provider:model id")
    parser.add_argument("--workspace", default=".", help="Working directory (default: .)")
    parser.add_argument("--session-id", default=None, help="Session id to write (default: new)")
    return parser


def run_task(workspace: Path, task: str, *, model: Optional[str] = None, session_id: Optional[str] = None) -> int:
    """Headless unattended run with JSONL persistence and the user's ~/.symphony config and rules."""
    load_provider_env(workspace)
    if not has_configured_provider():
        print("error: no provider credentials configured", file=sys.stderr)
        return 1
    agent = build_agent(
        workspace=workspace, sink=LogLineSink(), model_id=model, session_id=session_id,
        config=ensure_spawn_settings(workspace, overrides={"unattended": True}),
    )
    print(f"session {agent.session_id}", flush=True)

    async def _run() -> str:
        result = await agent.run(task)
        await agent.wait_for_learning()
        return result.output_text

    try:
        print(asyncio.run(_run()), flush=True)
    except Exception as exc:
        print(f"run failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


def continue_interrupted(workspace: Path, *, model: Optional[str] = None) -> int:
    found = asyncio.run(interrupted_session(JsonlPersistence(sessions_dir(workspace))))
    if found is None:
        print("nothing to continue: the most recent session was not interrupted mid-run")
        return 0
    summary, checkpoint = found
    stopped = stop_orphaned_jobs(checkpoint.metadata.get("background_jobs"))
    print(f"continuing interrupted session {summary.session_id} unattended", flush=True)
    return run_task(workspace, resume_note(summary, checkpoint, stopped), model=model, session_id=summary.session_id)


def main(argv: Sequence[str]) -> int:
    argv = list(argv)
    args = build_parser().parse_args(argv)
    workspace = Path(args.workspace).expanduser().resolve()
    if args.detach:
        return detach([arg for arg in argv if arg != "--detach"], workspace)
    return run_task(workspace, args.task, model=args.model, session_id=args.session_id)
