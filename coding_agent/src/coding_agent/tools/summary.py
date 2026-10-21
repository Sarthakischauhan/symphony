"""Counts that describe a finished tool call, shared by the stdio protocol and the TUI.

``summarize`` is pure: it reads the call's arguments, its result text, and the
facts the tool recorded for the call (search matches, the patch start line),
and fills only the counts that tool defines. Every other count is ``None``.
Nothing here parses a tool's result prose.
"""

from __future__ import annotations

from collections.abc import Mapping
from difflib import unified_diff
from typing import TypedDict


class ToolSummary(TypedDict):
    """The protocol 3 ``summary`` of a finished tool call."""

    lines: int | None
    matches: int | None
    added: int | None
    removed: int | None
    # 1-based file line where a patch's (first) old_str match starts.
    start_line: int | None


def _text(arguments: Mapping[str, object], key: str) -> str:
    value = arguments.get(key)
    return value if isinstance(value, str) else ""


def _line_count(text: str) -> int:
    return len(text.splitlines())


def diff_counts(old: str, new: str) -> tuple[int, int]:
    """Lines added and removed when ``old`` becomes ``new``."""
    added = removed = 0
    for line in unified_diff(old.splitlines(), new.splitlines(), lineterm=""):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


def summarize(
    tool_name: str,
    arguments: Mapping[str, object],
    result: str,
    *,
    failed: bool = False,
    matches: int | None = None,
    start_line: int | None = None,
) -> ToolSummary:
    """Counts for one finished call.

    ``matches`` is the number of results the search tool recorded and
    ``start_line`` the line the patch or read_file tool recorded
    (``PatchTool.start_lines``, ``ReadFileTool.start_lines``).
    """
    summary = ToolSummary(lines=None, matches=None, added=None, removed=None, start_line=None)
    if tool_name == "bash":
        summary["lines"] = _line_count(result)
    elif failed:
        return summary
    elif tool_name == "read_file":
        summary["lines"] = _line_count(result)
        summary["start_line"] = start_line
    elif tool_name == "search":
        summary["matches"] = matches
    elif tool_name == "write_file":
        lines = _line_count(_text(arguments, "content"))
        summary["lines"] = summary["added"] = lines
    elif tool_name == "patch":
        added, removed = diff_counts(_text(arguments, "old_str"), _text(arguments, "new_str"))
        summary["added"], summary["removed"] = added, removed
        summary["start_line"] = start_line
    return summary


__all__ = ["ToolSummary", "diff_counts", "summarize"]
