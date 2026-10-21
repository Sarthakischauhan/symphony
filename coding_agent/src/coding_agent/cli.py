"""The ``symphony`` command: route subcommands, else open the TUI.

Each subcommand is imported only when chosen, so ``web``, ``stdio``, ``acp``,
``bench`` and ``run`` never load Textual or ``coding_agent.tui``.
"""

from __future__ import annotations

import sys


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else None
    if command in {"--version", "-V"}:
        from importlib.metadata import PackageNotFoundError, version

        try:
            value = version("symphony-code")
        except PackageNotFoundError:
            value = "unknown"
        print(f"symphony {value}")
        return
    if command == "web":
        from coding_agent.web.server import main as web_main

        raise SystemExit(web_main(sys.argv[2:]))
    if command == "stdio":
        from coding_agent.protocols.stdio.server import main as stdio_main

        raise SystemExit(stdio_main(sys.argv[2:]))
    if command == "acp":
        from coding_agent.protocols.acp.server import main as acp_main

        raise SystemExit(acp_main(sys.argv[2:]))
    if command == "bench":
        from coding_agent.bench.cli import main as bench_main

        raise SystemExit(bench_main(sys.argv[2:]))
    if command == "run":
        from coding_agent.run.cli import main as run_main

        raise SystemExit(run_main(sys.argv[2:]))
    from coding_agent.tui.__main__ import main as tui_main

    tui_main()


if __name__ == "__main__":
    main()
