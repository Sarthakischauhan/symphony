"""Display-ready unified diffs for the patch tool widget."""

from __future__ import annotations

from difflib import unified_diff

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
