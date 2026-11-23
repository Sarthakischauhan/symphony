"""What kind of work a tool call is, and the counted labels that fold headers use.

The transcript folds tool calls the way Grok Build's scrollback does:

- Exploring calls (reading, searching) are quiet and come in bursts, so a run of
  them folds into one header that counts what happened: "Read 3 files,
  Searched 2 patterns".
- Every other call (an edit, a command, a subagent) changes something, so it
  keeps a one-line row of its own that expands in place.
- When a run of rows grows past ``VISIBLE_ROWS``, the older rows hide behind a
  header labelled the same way: "Edited 8 files, Ran 3 commands".

Both headers name the kinds in the order they first appear. Verbs are present
tense while any member still runs. Reads and edits count distinct files, so six
edits to one file read "Edited 1 file".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

# Tools whose runs fold into a counted header.
EXPLORE_TOOLS = frozenset({"read_file", "search", "web_search"})
# Rows of a dense run shown before older ones fold behind a header.
VISIBLE_ROWS = 10


@dataclass(frozen=True)
class Kind:
    past: str
    present: str
    one: str
    many: str


_KINDS: dict[str, Kind] = {
    "read_file": Kind("Read", "Reading", "file", "files"),
    "search": Kind("Searched", "Searching", "pattern", "patterns"),
    "web_search": Kind("Searched", "Searching", "web query", "web queries"),
    "patch": Kind("Edited", "Editing", "file", "files"),
    "write_file": Kind("Wrote", "Writing", "file", "files"),
    "bash": Kind("Ran", "Running", "command", "commands"),
    "spawn_agent": Kind("Ran", "Running", "subagent", "subagents"),
    "ask_user": Kind("Asked", "Asking", "question", "questions"),
    "generate_image": Kind("Generated", "Generating", "image", "images"),
    "save_artifact": Kind("Saved", "Saving", "artifact", "artifacts"),
}
_OTHER = Kind("Ran", "Running", "tool", "tools")
# Kinds counted by distinct path rather than by call.
_BY_PATH = frozenset({"read_file", "patch", "write_file"})


@dataclass(frozen=True)
class CountedCall:
    """The few facts a fold label needs about one call."""

    tool_name: str
    path: str = ""
    running: bool = False
    failed: bool = False


def is_exploring(tool_name: str) -> bool:
    return tool_name in EXPLORE_TOOLS


def kind_of(tool_name: str) -> Kind:
    return _KINDS.get(tool_name, _OTHER)


def counted_label(calls: Iterable[CountedCall]) -> tuple[str, bool, int]:
    """("Read 3 files, Searched 2 patterns", any running, failed count).

    One bucket per kind, in first-appearance order. Kinds that share words
    (two "Ran" kinds) stay separate buckets: "Ran 2 commands, Ran 1 tool".
    """
    counts: dict[Kind, int] = {}
    seen_paths: dict[Kind, set[str]] = {}
    running = False
    failed = 0
    for call in calls:
        kind = kind_of(call.tool_name)
        counts.setdefault(kind, 0)
        if call.tool_name in _BY_PATH and call.path:
            paths = seen_paths.setdefault(kind, set())
            if call.path not in paths:
                paths.add(call.path)
                counts[kind] += 1
        else:
            counts[kind] += 1
        running = running or call.running
        failed += call.failed
    parts = []
    for kind, count in counts.items():
        verb = kind.present if running else kind.past
        parts.append(f"{verb} {count} {kind.one if count == 1 else kind.many}")
    return ", ".join(parts), running, failed


__all__ = ["CountedCall", "EXPLORE_TOOLS", "VISIBLE_ROWS", "counted_label", "is_exploring", "kind_of"]
