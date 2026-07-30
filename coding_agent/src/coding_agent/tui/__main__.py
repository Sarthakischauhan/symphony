"""python -m coding_agent.tui"""

from __future__ import annotations

import argparse

from coding_agent.tui.app import run_tui


def main() -> None:
    parser = argparse.ArgumentParser(description="Symphony coding agent TUI")
    parser.add_argument(
        "--workspace",
        default=".workspace",
        help="Workspace directory for file/shell tools (default: .workspace or CODING_AGENT_WORKSPACE)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model id (default: OPENAI_MODEL or openai:gpt-4o-mini)",
    )
    args = parser.parse_args()
    run_tui(workspace=args.workspace, model_id=args.model)


if __name__ == "__main__":
    main()
