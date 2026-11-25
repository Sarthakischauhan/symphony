#!/usr/bin/env python3
"""Validate a Conventional Commits header (one message file argument)."""
import re
import sys
from pathlib import Path

HEADER = re.compile(r"(?:feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(?:\([a-zA-Z0-9][a-zA-Z0-9._/-]*\))?!?: [^\s].*")


def main() -> int:
    header = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()[0] if len(sys.argv) == 2 and Path(sys.argv[1]).stat().st_size else ""
    if HEADER.fullmatch(header):
        return 0
    print(f"Invalid commit subject: {header!r}\nUse type(scope): description, e.g. fix(memory): handle empty capture", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
