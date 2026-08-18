"""python -m coding_agent.tui"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from coding_agent.persistence import SqlitePersistence
from coding_agent.tui.app import run_tui
from coding_agent.tui.resume import ResumeApp, load_session_options


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
        help="Model id (default: OPENAI_MODEL or openai:gpt-5.6-luna)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="List saved sessions and interactively resume one",
    )
    parser.add_argument(
        "--learn",
        action="store_true",
        help="Enable optional post-run learning / reflection",
    )
    args = parser.parse_args()
    workspace = Path(args.workspace or ".").resolve()
    session_id = None
    if args.resume:
        persistence = SqlitePersistence(workspace / ".symphony" / "sessions.sqlite3")
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
        enable_learning=args.learn,
    )


if __name__ == "__main__":
    main()
