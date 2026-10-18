"""One process owns one session; reuse the existing stdio interaction protocol."""

import asyncio
import sys
from pathlib import Path

from coding_agent.addons.persistence import register_active, release_active
from coding_agent.protocols import stdio


def main():
    workspace, session_id, model = sys.argv[1:]
    try:
        register_active(session_id, workspace=workspace, kind="web")
        sys.stdout = sys.stderr
        return asyncio.run(stdio.serve(Path(workspace), model or None, session_id, client="tui"))
    finally:
        release_active()


if __name__ == "__main__":
    raise SystemExit(main())
