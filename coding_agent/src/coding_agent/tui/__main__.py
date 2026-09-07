"""python -m coding_agent.tui"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from coding_agent.persistence import JsonlPersistence, sessions_dir
from coding_agent.tui.app import run_tui
from coding_agent.tui.screens.resume import ResumeApp, load_session_options


def main() -> None:
    parser = argparse.ArgumentParser(description="Symphony coding agent TUI")
    parser.add_argument(
        "--workspace",
        default=None,
        help="Workspace directory for file/shell tools (default: current directory)",
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
    parser.set_defaults(enable_learning=None)
    args = parser.parse_args()
    workspace = Path(args.workspace or ".").resolve()
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
    )


if __name__ == "__main__":
    main()
