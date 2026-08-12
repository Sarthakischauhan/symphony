"""python -m coding_agent.tui"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from coding_agent.persistence import SqlitePersistence
from coding_agent.tui.app import run_tui


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
    args = parser.parse_args()
    workspace = Path(args.workspace or ".").resolve()
    session_id = None
    if args.resume:
        sessions = asyncio.run(
            SqlitePersistence(workspace / ".symphony" / "sessions.sqlite3").list_sessions()
        )
        if not sessions:
            parser.error(f"no saved sessions found in {workspace / '.symphony' / 'sessions.sqlite3'}")
        print("Saved sessions:")
        for index, session in enumerate(sessions, start=1):
            print(f"  {index}. {session.session_id} ({session.updated_at})")
        try:
            selection = int(input("Resume session number: "))
            session_id = sessions[selection - 1].session_id
        except (ValueError, IndexError):
            parser.error("invalid session selection")
    run_tui(workspace=workspace, model_id=args.model, session_id=session_id)


if __name__ == "__main__":
    main()
