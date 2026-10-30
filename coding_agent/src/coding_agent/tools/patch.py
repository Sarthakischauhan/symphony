"""Surgical exact-text editing."""

from __future__ import annotations

import difflib
from pathlib import Path

from core_harness.tools import current_tool_call_id
from pydantic import ConfigDict, Field

from coding_agent.tools.base import NonEmptyPath, ToolArgsModel, WorkspaceTool

CHAR_FOLD = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2212": "-",
        "\u00a0": " ",
        "\u202f": " ",
        "\u2009": " ",
    }
)


class PatchArgs(ToolArgsModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    path: NonEmptyPath = Field(
        ...,
        min_length=1,
        description="Existing file path. Relative paths start at the working directory.",
    )
    old_str: str = Field(..., min_length=1, description="Exact whitespace-significant text to replace.")
    new_str: str = Field(..., description="Exact replacement text; empty deletes the match.")
    replace_all: bool = Field(default=False, description="Replace all matches instead of requiring one.")


class PatchTool(WorkspaceTool):
    name = "patch"
    description = (
        "Replace one exact span in an existing text file. old_str must match the "
        "file, including indentation. A unique whitespace or quote difference still "
        "matches; several matches need replace_all or a longer old_str. A miss "
        "returns nearby lines and changes nothing."
    )
    args_model = PatchArgs

    def __init__(self, workspace: str | Path) -> None:
        # Where each applied patch's (first) old_str matched, as a 1-based line
        # of the file before the edit, keyed by tool_call_id. EventFields reads
        # it for the protocol summary's ``start_line``, the way it reads
        # ``BashTool.exit_codes``.
        self.start_lines: dict[str, int] = {}
        super().__init__(workspace)

    def run(self, path: str, old_str: str, new_str: str, replace_all: bool = False) -> str:
        old = to_lf(old_str)
        new = to_lf(new_str)
        if old == new:
            return f"noop: old_str and new_str are identical in {path}; no change"
        try:
            target = self.resolve_path(path)
        except (TypeError, ValueError) as exc:
            return f"error: {exc}"
        if not target.exists():
            return f"error: file not found: {path}"
        if not target.is_file():
            return f"error: not a file: {path}"
        try:
            with target.open("r", encoding="utf-8", newline="") as handle:
                original = handle.read()
        except UnicodeDecodeError:
            return f"error: file is not valid UTF-8 text: {path}"
        except OSError as exc:
            return f"error: failed to read {path}: {exc}"

        bom = "\ufeff" if original.startswith("\ufeff") else ""
        body = original[len(bom) :]
        ending = "\r\n" if "\r\n" in body else "\n"
        base = to_lf(body)

        locations = match_lines(base, old)
        if locations:
            count = len(locations)
            if count > 1 and not replace_all:
                return ambiguous_match(path, locations)
            updated_base = base.replace(old, new) if replace_all else base.replace(old, new, 1)
            replaced = count if replace_all else 1
            starts = locations if replace_all else locations[:1]
        else:
            windows = relaxed_windows(base, old)
            if not windows:
                already = (
                    f"\nnote: {path} already contains new_str; this hunk may already be applied"
                    if new and new in base
                    else ""
                )
                return f"old_str not found in {path}{already}\n{mismatch_hints(base, old)}"
            if len(windows) > 1 and not replace_all:
                return ambiguous_match(path, [start + 1 for start in windows])
            used = windows if replace_all else windows[:1]
            updated_base = replace_windows(base, old, new, used)
            replaced = len(used)
            # Folded matches are line windows; report them 1-based like exact ones.
            starts = [start + 1 for start in used]

        updated = bom + from_lf(updated_base, ending)
        try:
            with target.open("w", encoding="utf-8", newline="") as handle:
                handle.write(updated)
        except OSError as exc:
            return f"error: failed to write {path}: {exc}"
        call_id = current_tool_call_id.get()
        if call_id:
            self.start_lines[call_id] = starts[0]
        delta = len(updated.encode("utf-8")) - len(original.encode("utf-8"))
        return f"patched {path} {at_lines(starts)} ({replaced} replacement(s), {delta:+d} bytes)"


def at_lines(starts: list[int]) -> str:
    """Where old_str matched, as 1-based lines of the file before the edit."""
    shown = ", ".join(str(n) for n in starts[:8])
    extra = f" (+{len(starts) - 8} more)" if len(starts) > 8 else ""
    return f"at line {shown}" if len(starts) == 1 else f"at lines {shown}{extra}"


def to_lf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def from_lf(text: str, ending: str) -> str:
    return text.replace("\n", ending) if ending != "\n" else text


def content_lines(text: str) -> list[str]:
    if text == "":
        return []
    parts = text.split("\n")
    return parts[:-1] if text.endswith("\n") else parts


def visible(text: str) -> str:
    return text.replace("\r", "␍").replace("\t", "→").replace(" ", "·")


def match_lines(text: str, needle: str) -> list[int]:
    lines: list[int] = []
    start = 0
    step = max(len(needle), 1)
    while True:
        index = text.find(needle, start)
        if index < 0:
            return lines
        lines.append(text.count("\n", 0, index) + 1)
        start = index + step


def relaxed_windows(base: str, old: str) -> list[int]:
    """0-based starts of folded line windows matching ``old``, without overlaps.

    Like ``match_lines``, a match resumes after the previous one ends, so
    ``replace_all`` never rewrites a line twice.
    """
    hay = [line.translate(CHAR_FOLD).rstrip() for line in content_lines(base)]
    ned = [line.translate(CHAR_FOLD).rstrip() for line in content_lines(old)]
    n = len(ned)
    if n == 0 or n > len(hay):
        return []
    starts: list[int] = []
    for i in range(len(hay) - n + 1):
        if (not starts or i >= starts[-1] + n) and hay[i : i + n] == ned:
            starts.append(i)
    return starts


def replace_windows(base: str, old: str, new: str, starts: list[int]) -> str:
    hay = base.split("\n")
    n_old = len(content_lines(old))
    new_lines = content_lines(new)
    for start in reversed(starts):
        hay[start : start + n_old] = new_lines
    return "\n".join(hay)


def ambiguous_match(path: str, locations: list[int]) -> str:
    count = len(locations)
    shown = ", ".join(f"line {n}" for n in locations[:8])
    extra = f" (+{count - 8} more)" if count > 8 else ""
    return (
        f"old_str matched {count} times in {path} ({shown}{extra}); "
        "not applying. Add surrounding lines to make it unique, or set "
        "replace_all=true."
    )


def mismatch_hints(original: str, old_str: str) -> str:
    file_lines = original.splitlines()
    needle = (old_str.splitlines() or [old_str])[0]
    stripped = needle.strip()
    notes: list[str] = []
    crlf = original.count("\r\n")
    lf = original.count("\n") - crlf
    if crlf > lf and "\r" not in old_str:
        notes.append("file uses CRLF line endings; old_str does not")

    ws_hits: list[tuple[int, str]] = []
    if stripped:
        for number, line in enumerate(file_lines, 1):
            if line.strip() == stripped and line != needle:
                ws_hits.append((number, line))
                if len(ws_hits) >= 3:
                    break
    if ws_hits:
        notes.append("closest lines (whitespace differs; ·=space →=tab):")
        for number, line in ws_hits:
            notes.append(f"  {number}|{visible(line)}")
        notes.append(f"  old|{visible(needle)}")
        return "\n".join(notes)

    pool = file_lines
    if len(pool) > 2000 and stripped:
        token = stripped[:8]
        narrowed = [line for line in file_lines if token in line][:400]
        pool = narrowed or file_lines[:400]
    close = difflib.get_close_matches(needle, pool, n=3, cutoff=0.55)
    if close:
        notes.append("closest lines:")
        for candidate in close:
            try:
                number = file_lines.index(candidate) + 1
            except ValueError:
                number = "?"
            notes.append(f"  {number}|{visible(candidate)}")
        notes.append(f"  old|{visible(needle)}")
        return "\n".join(notes)

    notes.append("no similar lines found; re-read the file and copy the exact text")
    return "\n".join(notes)
