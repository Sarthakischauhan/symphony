"""Counts that describe a finished tool call, shared by the stdio protocol and the TUI.

``summarize`` is pure: it reads the call's arguments and its result text and
fills only the counts that tool defines. Every other count is ``None``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from difflib import unified_diff
from typing import TypedDict

# The search tool's first line: "<N> content matches" or "<N> files matches".
_SEARCH_HEADER = re.compile(r"^(\d+) (?:content|files) matches")
# The patch tool's result: "patched <path> at line <N> (...)" or "at lines <N>, <M> (...)".
_PATCH_AT = re.compile(r"^patched .+ at lines? (\d+)(?:, \d+)*(?: \(\+\d+ more\))? \(\d+ replacement")


class ToolSummary(TypedDict):
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


def patch_start_line(result: str) -> int | None:
    """The first matched line a patch result reports, or None for older results."""
    found = _PATCH_AT.match(result)
    return int(found.group(1)) if found else None


def diff_counts(old: str, new: str) -> tuple[int, int]:
    """Lines added and removed when ``old`` becomes ``new``."""
    added = removed = 0
    for line in unified_diff(old.splitlines(), new.splitlines(), lineterm=""):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


def summarize(tool_name: str, arguments: Mapping[str, object], result: str, *, failed: bool = False) -> ToolSummary:
    summary = ToolSummary(lines=None, matches=None, added=None, removed=None, start_line=None)
    if tool_name == "bash":
        summary["lines"] = _line_count(result)
    elif failed:
        return summary
    elif tool_name == "read_file":
        summary["lines"] = _line_count(result)
    elif tool_name == "search":
        header = _SEARCH_HEADER.match(result)
        summary["matches"] = int(header.group(1)) if header else 0
    elif tool_name == "write_file":
        lines = _line_count(_text(arguments, "content"))
        summary["lines"] = summary["added"] = lines
    elif tool_name == "patch":
        added, removed = diff_counts(_text(arguments, "old_str"), _text(arguments, "new_str"))
        summary["added"], summary["removed"] = added, removed
        summary["start_line"] = patch_start_line(result)
    return summary


__all__ = ["ToolSummary", "diff_counts", "patch_start_line", "summarize"]
