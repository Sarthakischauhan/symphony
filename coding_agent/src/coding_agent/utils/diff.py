"""Workspace and text-diff helpers."""

from __future__ import annotations

import subprocess
from difflib import unified_diff
from pathlib import Path


def read_workspace_diff(workspace: Path) -> str:
    """Return the current workspace diff, or a user-facing failure message."""
    try:
        result = subprocess.run(
            ["git", "-C", str(workspace), "diff", "--unified=0", "--", "."],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception as exc:  # noqa: BLE001
        return f"Failed to run git diff: {exc}"

    output = (result.stdout or "").strip()
    if output:
        return output
    if result.returncode != 0:
        err = (result.stderr or "").strip()
        return err or "git diff failed"
    return "No local changes found."


def split_diff(diff_text: str) -> list[tuple[str, str]]:
    """Split a Git diff into a path and body for each changed file."""
    files: list[tuple[str, str]] = []
    path = ""
    lines: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            if path:
                files.append((path, "\n".join(lines)))
            paths = line.removeprefix("diff --git ")
            path = paths.split(" b/", 1)[-1].removeprefix("b/")
            lines = []
        elif line.startswith(("index ", "--- ", "+++ ", "new file", "deleted file")):
            continue
        elif path:
            lines.append(line)

    if path:
        files.append((path, "\n".join(lines)))
    return files


def make_unified_diff(old: str, new: str, path: str) -> list[str]:
    """Build display-ready unified diff lines for an exact-text edit."""
    if not old and not new:
        return []
    lines = list(
        unified_diff(
            old.splitlines(),
            new.splitlines(),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        )
    )
    return lines[2:] if len(lines) >= 2 else lines


def diff_stats(diff: list[str]) -> tuple[int, int]:
    """Count additions and deletions in display-ready diff lines."""
    additions = sum(line.startswith("+") and not line.startswith("+++") for line in diff)
    deletions = sum(line.startswith("-") and not line.startswith("---") for line in diff)
    return int(additions), int(deletions)
