"""One process owns one session: the stdio protocol, run as the ``web`` client.

The host passes ``--session-id`` for every worker (a fresh id for a new
session), the same flag Zeron uses to resume, so this process can claim the
session's lifetime lock before the agent opens it.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from coding_agent.addons.persistence import register_active, release_active
from coding_agent.protocols.stdio import write_frame
from coding_agent.protocols.stdio.server import main as stdio_main


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="symphony web worker", add_help=False)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--session-id", required=True)
    known, _ = parser.parse_known_args(args)
    try:
        try:
            register_active(known.session_id, workspace=known.workspace, kind="web")
        except RuntimeError as exc:
            # The host reads this like any other startup error frame.
            write_frame({"type": "error", "message": str(exc)})
            return 1
        return stdio_main([*args, "--client", "web"])
    finally:
        release_active()


if __name__ == "__main__":
    raise SystemExit(main())
