"""python -m coding_agent.tui"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from coding_agent.persistence import JsonlPersistence, sessions_dir
from coding_agent.tui.app import run_tui
from coding_agent.tui.screens.resume import ResumeApp, load_session_options


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Symphony coding agent TUI")
    parser.add_argument(
        "--workspace",
        default=None,
        help="Working directory for relative paths and bash cwd (default: .)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model id (default: SYMPHONY_MODEL, OPENAI_MODEL, or first available provider)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="List saved sessions and interactively resume one",
    )
    parser.add_argument(
        "--continue",
        dest="continue_run",
        action="store_true",
        help="With --resume: continue the most recent session unattended if it was interrupted mid-run",
    )
    learning = parser.add_mutually_exclusive_group()
    learning.add_argument(
        "--learn",
        dest="enable_learning",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    learning.add_argument(
        "--no-learning",
        dest="enable_learning",
        action="store_false",
        help="Disable post-run learning / reflection",
    )
    parser.add_argument(
        "--jev",
        dest="enable_jev",
        action="store_true",
        default=None,
        help="Enable Jev critic mode (findings only; does not switch the chat model)",
    )
    parser.add_argument(
        "--unattended",
        action="store_true",
        help="No human in the loop: auto-approve (deny rules still apply) and auto-answer ask_user",
    )
    parser.set_defaults(enable_learning=None)
    return parser


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "bench":
        from coding_agent.bench.cli import main as bench_main

        raise SystemExit(bench_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        from coding_agent.run.cli import main as run_main

        raise SystemExit(run_main(sys.argv[2:]))
    parser = build_parser()
    args = parser.parse_args()
    workspace = Path(args.workspace or ".").resolve()
    if args.continue_run:
        if not args.resume:
            parser.error("--continue requires --resume")
        from coding_agent.run.cli import continue_interrupted

        raise SystemExit(continue_interrupted(workspace, model=args.model))
    session_id = None
    if args.resume:
        persistence = JsonlPersistence(sessions_dir(workspace))
        sessions = asyncio.run(load_session_options(persistence))
        if not sessions:
            parser.error("no saved sessions found")
        session_id = ResumeApp(sessions).run()
        if session_id is None:
            return
    run_tui(
        workspace=workspace,
        model_id=args.model,
        session_id=session_id,
        enable_learning=args.enable_learning,
        enable_jev=args.enable_jev,
        unattended=args.unattended,
    )


if __name__ == "__main__":
    main()
