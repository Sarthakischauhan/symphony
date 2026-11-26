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


class CallTally:
    """Running totals for one fold header.

    Adding or replacing a call touches one bucket. Rebuilding the label from
    every call on each status change was quadratic in the size of the group.
    """

    def __init__(self) -> None:
        self.counts: dict[Kind, int] = {}
        # How many current calls name each path. Distinct files are the
        # counts; a second read of the same file must not drop the file when
        # the first read is removed.
        self.paths: dict[Kind, dict[str, int]] = {}
        self.running = 0
        self.failed = 0

    def add(self, call: CountedCall) -> None:
        kind = kind_of(call.tool_name)
        self.counts.setdefault(kind, 0)
        if call.tool_name in _BY_PATH and call.path:
            seen = self.paths.setdefault(kind, {})
            seen[call.path] = seen.get(call.path, 0) + 1
            if seen[call.path] == 1:
                self.counts[kind] += 1
        else:
            self.counts[kind] += 1
        self.running += call.running
        self.failed += call.failed

    def remove(self, call: CountedCall) -> None:
        kind = kind_of(call.tool_name)
        if call.tool_name in _BY_PATH and call.path:
            seen = self.paths.get(kind)
            count = seen.get(call.path, 0) if seen is not None else 0
            if count:
                assert seen is not None
                if count == 1:
                    del seen[call.path]
                    self.counts[kind] -= 1
                else:
                    seen[call.path] = count - 1
        elif kind in self.counts:
            self.counts[kind] -= 1
        self.running -= call.running
        self.failed -= call.failed

    def label(self) -> str:
        running = self.running > 0
        parts = []
        for kind, count in self.counts.items():
            if count <= 0:
                continue
            verb = kind.present if running else kind.past
            parts.append(f"{verb} {count} {kind.one if count == 1 else kind.many}")
        return ", ".join(parts)


def counted_label(calls: Iterable[CountedCall]) -> tuple[str, bool, int]:
    """("Read 3 files, Searched 2 patterns", any running, failed count).

    One bucket per kind, in first-appearance order. Kinds that share words
    (two "Ran" kinds) stay separate buckets: "Ran 2 commands, Ran 1 tool".
    """
    tally = CallTally()
    for call in calls:
        tally.add(call)
    return tally.label(), tally.running > 0, tally.failed


__all__ = [
    "CallTally",
    "CountedCall",
    "EXPLORE_TOOLS",
    "VISIBLE_ROWS",
    "counted_label",
    "is_exploring",
    "kind_of",
]
