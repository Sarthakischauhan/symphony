#!/usr/bin/env python3
"""Dump or check the Symphony TUI theme.toml.

    uv run python scripts/theme.py
    uv run python scripts/theme.py --check
    uv run python scripts/theme.py --sync
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from coding_agent.tui.theme.load import (
    SYMPHONY_COLOR_KEYS,
    ThemeConfigError,
    ThemeDocument,
    find_repo_theme,
    load_theme,
    packaged_theme_path,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, help="theme.toml to load instead of the default")
    parser.add_argument(
        "--check",
        action="store_true",
        help="assert required tokens and that APP_CSS includes palette values",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="copy repo config/theme.toml onto the packaged theme.toml",
    )
    args = parser.parse_args(argv)

    try:
        if args.sync:
            return sync_packaged_copy()
        theme = load_theme(args.path)
        if args.check:
            return check_theme(theme, path=args.path)
        dump_theme(theme)
        return 0
    except ThemeConfigError as exc:
        print(f"theme: {exc}", file=sys.stderr)
        return 1


def dump_theme(theme: ThemeDocument) -> None:
    print(f"source: {theme.source}")
    print(f"colors ({len(theme.colors)}): {', '.join(theme.colors)}")
    print(
        "css: chrome tools composer resume onboard modal.base "
        "content image diff extensions learning plan context provider"
    )
    print(f"APP_CSS: {len(theme.app_css)} chars")


def check_theme(theme: ThemeDocument, *, path: Path | None) -> int:
    missing = [key for key in SYMPHONY_COLOR_KEYS if key not in theme.colors]
    if missing:
        print("missing color tokens: " + ", ".join(missing), file=sys.stderr)
        return 1
    if not theme.app_css.strip():
        print("APP_CSS is empty", file=sys.stderr)
        return 1
    for key in ("background", "accent"):
        value = theme.colors[key]
        if value not in theme.app_css:
            print(f"APP_CSS does not include {key} token {value}", file=sys.stderr)
            return 1
    repo = find_repo_theme() if path is None else None
    packaged = packaged_theme_path()
    if repo is not None and packaged.is_file() and repo.read_bytes() != packaged.read_bytes():
        print(
            f"packaged {packaged} does not match {repo}; run scripts/theme.py --sync",
            file=sys.stderr,
        )
        return 1
    dump_theme(theme)
    print("ok")
    return 0


def sync_packaged_copy() -> int:
    repo = find_repo_theme()
    if repo is None:
        print("repo config/theme.toml not found", file=sys.stderr)
        return 1
    packaged = packaged_theme_path()
    packaged.write_bytes(repo.read_bytes())
    print(f"copied {repo} -> {packaged}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
