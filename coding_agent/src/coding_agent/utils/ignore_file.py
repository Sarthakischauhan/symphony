"""Gitignore-aware ignore helpers for workspace tools."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

DEFAULT_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".tox",
}

Rule = tuple[re.Pattern, bool, bool]  # (regex, dir_only, negated)


def glob_to_regex(pattern: str) -> str:
    """Convert a gitignore-style glob into a regex fragment.

    ``*`` matches within a path segment, ``**`` crosses segments, and
    ``?`` matches one non-slash character.
    """
    i = 0
    n = len(pattern)
    out: list[str] = []
    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                out.append(".*")
                i += 2
            else:
                out.append("[^/]*")
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return "".join(out)


def parse_line(line: str) -> Rule | None:
    """Parse one gitignore line into a rule, or None to skip it.

    Supports the common subset: blank lines, ``#`` comments, ``!``
    negation, trailing ``/`` for directory-only rules, and ``/``-anchored
    patterns. Last matching rule wins.
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    negated = False
    if line.startswith("!"):
        negated = True
        line = line[1:].strip()
    if not line:
        return None
    dir_only = line.endswith("/")
    if dir_only:
        line = line.rstrip("/")
    anchored = line.startswith("/")
    line = line.lstrip("/")
    if anchored or "/" in line:
        regex = re.compile(glob_to_regex(line))
    else:
        regex = re.compile(r"(?:.*/)?" + glob_to_regex(line))
    return regex, dir_only, negated


def is_matched(rules: tuple[Rule, ...], rel_path: str, is_dir: bool) -> bool | None:
    """Last matching rule's ignore status, or None if no rule matched."""
    result = None
    for regex, dir_only, negated in rules:
        if dir_only and not is_dir:
            continue
        if regex.fullmatch(rel_path):
            result = not negated
    return result


def rel_ignored(rules: tuple[Rule, ...], rel_path: str) -> bool:
    """Whether ``rel_path`` (posix) is ignored, checking each ancestor dir."""
    if rel_path in (".", ""):
        return False
    parts = rel_path.split("/")
    ignored = False
    for i in range(1, len(parts) + 1):
        candidate = "/".join(parts[:i])
        m = is_matched(rules, candidate, i < len(parts))
        if m is True:
            ignored = True
        elif m is False and not ignored:
            ignored = False
    return ignored


@lru_cache(maxsize=128)
def load_rules(
    workspace: Path,
) -> tuple[tuple[Path, tuple[Rule, ...]], ...]:
    """Parse every .gitignore under the workspace, keyed by its parent dir."""
    matchers: list[tuple[Path, tuple[Rule, ...]]] = []
    if not workspace.exists():
        return tuple(matchers)
    for gif in workspace.rglob(".gitignore"):
        if any(part in DEFAULT_SKIP_DIRS for part in gif.parts):
            continue
        try:
            rules = tuple(filter(None, (parse_line(l) for l in gif.read_text(encoding="utf-8").splitlines())))
        except (OSError, UnicodeDecodeError):
            continue
        matchers.append((gif.parent, rules))
    return tuple(matchers)


def is_ignored(path: Path, workspace: Path) -> bool:
    """Whether ``path`` is matched by a .gitignore under ``workspace``."""
    for base, rules in load_rules(workspace):
        if path.is_relative_to(base) and rel_ignored(rules, path.relative_to(base).as_posix()):
            return True
    return False
