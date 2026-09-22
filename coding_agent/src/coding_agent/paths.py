"""Nearest enclosing project root.

Markers are checked in this order at each directory, then the walk continues
toward the filesystem root: ``pyproject.toml``, ``.git``, ``personalities.json``.
The first hit wins. No marker through the root yields ``None``.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT_MARKERS = ("pyproject.toml", ".git", "personalities.json")


def project_root(start: Path | None = None) -> Path | None:
    """Return the nearest project directory above ``start``, or ``None``.

    ``start`` defaults to the current working directory. A file path uses its
    parent. The walk stops at the filesystem root and will not loop.
    """
    try:
        current = (Path.cwd() if start is None else start).resolve()
    except OSError:
        return None
    if not current.is_dir():
        current = current.parent
    seen: set[Path] = set()
    while current not in seen:
        seen.add(current)
        if any((current / marker).exists() for marker in PROJECT_ROOT_MARKERS):
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None
