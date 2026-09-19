"""python -m coding_agent.tui"""

from __future__ import annotations

import argparse
import asyncio
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
    parser.set_defaults(enable_learning=None)
    return parser


def main() -> None:
    parser = build_parser()
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
        enable_jev=args.enable_jev,
    )


if __name__ == "__main__":
    main()
