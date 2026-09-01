"""Workspace-file suggestions for ``@path`` composer mentions."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from coding_agent.tools.search import DEFAULT_SKIP_DIRS, is_ignored

_ACTIVE_MENTION = re.compile(r"(?<!\S)@([^\s@]*)$")


@dataclass(frozen=True)
class FileOption:
    path: str
    description: str


def active_file_mention(value: str) -> tuple[int, str] | None:
    """Return the active mention's start and query when the cursor is at its end."""
    match = _ACTIVE_MENTION.search(value)
    if match is None:
        return None
    return match.start(), match.group(1)


def complete_file_mention(value: str, path: str) -> tuple[str, int]:
    """Replace the active ``@query`` while preserving the rest of the prompt."""
    active = active_file_mention(value)
    if active is None:
        completed = f"{value}@{path} "
        return completed, len(completed)
    start, _query = active
    completed = f"{value[:start]}@{path} "
    return completed, len(completed)


def file_matches(workspace: Path, query: str) -> tuple[FileOption, ...]:
    """Return all gitignore-aware file matches ranked by path relevance."""
    workspace = workspace.resolve()
    needle = query.strip().lower()
    candidates: list[tuple[tuple[int, int, int, str], FileOption]] = []

    for root, dirs, filenames in os.walk(workspace):
        root_path = Path(root)
        dirs[:] = [
            name
            for name in dirs
            if name not in DEFAULT_SKIP_DIRS
            and not name.startswith(".")
            and not is_ignored(root_path / name, workspace)
        ]
        for filename in filenames:
            path = root_path / filename
            relative = path.relative_to(workspace).as_posix()
            if filename.startswith(".") or is_ignored(path, workspace):
                continue
            relative_lower = relative.lower()
            filename_lower = filename.lower()
            if needle and needle not in relative_lower:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            rank = (
                0 if filename_lower.startswith(needle) else 1,
                0 if f"/{needle}" in relative_lower else 1,
                len(relative),
                relative_lower,
            )
            candidates.append((rank, FileOption(relative, _size_label(size))))

    candidates.sort(key=lambda item: item[0])
    return tuple(option for _rank, option in candidates)


def _size_label(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


__all__ = [
    "FileOption",
    "active_file_mention",
    "complete_file_mention",
    "file_matches",
]
