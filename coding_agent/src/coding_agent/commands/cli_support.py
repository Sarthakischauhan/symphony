"""What the ``skills`` and ``plugins`` command lines share: parsing that cannot exit the process, and tables.

The same parsers serve ``symphony skills ...`` in a shell and ``/skills ...`` in the
TUI and stdio, so a usage mistake is an error message in all three.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, NoReturn, Sequence


class UsageError(ValueError):
    """A command line that did not parse."""


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise UsageError(f"{message}\n\n{self.format_usage().strip()}")


@dataclass(frozen=True)
class Context:
    """Where a command runs: ``workspace`` picks project skills and plugins, ``cwd`` resolves relative paths."""

    workspace: Path
    cwd: Path


@dataclass(frozen=True)
class Outcome:
    """What a command printed, and whether it changed what the agent should load."""

    text: str
    changed: bool = False
    ok: bool = True


def table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    widths = [max(len(str(row[i])) for row in [header, *rows]) for i in range(len(header))]
    lines = ["  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)).rstrip() for row in [header, *rows]]
    return "\n".join(lines)


def run_command(
    argv: Sequence[str],
    context: Context,
    build: Callable[[], Parser],
    execute: Callable[[argparse.Namespace, Context], Outcome],
) -> Outcome:
    """Parse ``argv`` and run it. Usage mistakes and failures come back as text, never as an exit."""
    parser = build()
    if not argv or argv[0] in {"-h", "--help"}:
        return Outcome(parser.format_help().rstrip())
    try:
        arguments = parser.parse_args(list(argv))
        return execute(arguments, context)
    except UsageError as exc:
        return Outcome(f"error: {exc}", ok=False)
    except ValueError as exc:
        return Outcome(f"error: {exc}", ok=False)


def main(
    argv: Sequence[str],
    build: Callable[[], Parser],
    execute: Callable[[argparse.Namespace, Context], Outcome],
) -> int:
    """Entry point of ``symphony skills|plugins``: print the outcome, exit 1 on an error."""
    outcome = run_command(argv, Context(Path.cwd(), Path.cwd()), build, execute)
    print(outcome.text, file=sys.stdout if outcome.ok else sys.stderr)
    return 0 if outcome.ok else 1


__all__ = ["Context", "Outcome", "Parser", "UsageError", "main", "run_command", "table"]
