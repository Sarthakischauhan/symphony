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


@dataclass(frozen=True)
class _IndexedFile:
    path: str
    name: str
    size: int


class WorkspaceFileIndex:
    """Walk the workspace once, then filter in memory until invalidated."""

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).resolve()
        self._entries: tuple[_IndexedFile, ...] | None = None

    def invalidate(self) -> None:
        self._entries = None

    def matches(self, query: str) -> tuple[FileOption, ...]:
        if self._entries is None:
            self._entries = _scan_workspace(self.workspace)
        return _rank_files(self._entries, query)


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


def file_matches(
    workspace: Path,
    query: str,
    *,
    index: WorkspaceFileIndex | None = None,
) -> tuple[FileOption, ...]:
    """Return gitignore-aware file matches ranked by path relevance."""
    if index is None or index.workspace != Path(workspace).resolve():
        index = WorkspaceFileIndex(workspace)
    return index.matches(query)


def _scan_workspace(workspace: Path) -> tuple[_IndexedFile, ...]:
    entries: list[_IndexedFile] = []
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
            if filename.startswith(".") or is_ignored(path, workspace):
                continue
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            entries.append(
                _IndexedFile(path.relative_to(workspace).as_posix(), filename, size)
            )
    return tuple(entries)


def _rank_files(entries: tuple[_IndexedFile, ...], query: str) -> tuple[FileOption, ...]:
    needle = query.strip().lower()
    ranked: list[tuple[tuple[int, int, int, str], FileOption]] = []
    for entry in entries:
        relative_lower = entry.path.lower()
        name_lower = entry.name.lower()
        if needle and needle not in relative_lower:
            continue
        rank = (
            0 if name_lower.startswith(needle) else 1,
            0 if f"/{needle}" in relative_lower else 1,
            len(entry.path),
            relative_lower,
        )
        ranked.append((rank, FileOption(entry.path, _size_label(entry.size))))
    ranked.sort(key=lambda item: item[0])
    return tuple(option for _rank, option in ranked)


def _size_label(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


__all__ = [
    "FileOption",
    "WorkspaceFileIndex",
    "active_file_mention",
    "complete_file_mention",
    "file_matches",
]
