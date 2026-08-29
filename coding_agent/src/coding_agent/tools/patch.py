"""Surgical exact-text editing for workspace files."""

from __future__ import annotations

import difflib

from pydantic import ConfigDict, Field, field_validator

from coding_agent.tools.base import ToolArgsModel, WorkspaceTool


class PatchArgs(ToolArgsModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    path: str = Field(..., min_length=1, description="Workspace-relative existing file path.")
    old_str: str = Field(..., min_length=1, description="Exact whitespace-significant text to replace.")
    new_str: str = Field(..., description="Exact replacement text; empty deletes the match.")
    replace_all: bool = Field(default=False, description="Replace all matches instead of requiring one.")

    @field_validator("path")
    @classmethod
    def _strip_path_only(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("path must be a non-empty string")
        return stripped


class PatchTool(WorkspaceTool):
    name = "patch"
    description = (
        "Replace exact text in an existing UTF-8 file; whitespace is significant. "
        "On a miss the result lists nearby lines instead of failing. Identical "
        "old_str/new_str is a no-op."
    )
    args_model = PatchArgs

    def run(self, path: str, old_str: str, new_str: str, replace_all: bool = False) -> str:
        if old_str == new_str:
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
            original = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return f"error: file is not valid UTF-8 text: {path}"
        except OSError as exc:
            return f"error: failed to read {path}: {exc}"

        locations = _match_lines(original, old_str)
        count = len(locations)
        if count == 0:
            already = (
                f"\nnote: {path} already contains new_str; this hunk may already be applied"
                if new_str and new_str in original
                else ""
            )
            return f"old_str not found in {path}{already}\n{_mismatch_hints(original, old_str)}"
        if count > 1 and not replace_all:
            shown = ", ".join(f"line {n}" for n in locations[:8])
            extra = f" (+{count - 8} more)" if count > 8 else ""
            return (
                f"old_str matched {count} times in {path} ({shown}{extra}); "
                "not applying. Add surrounding lines to make it unique, or set "
                "replace_all=true."
            )
        updated = original.replace(old_str, new_str) if replace_all else original.replace(old_str, new_str, 1)
        try:
            target.write_text(updated, encoding="utf-8")
        except OSError as exc:
            return f"error: failed to write {path}: {exc}"
        replaced = count if replace_all else 1
        delta = len(updated.encode("utf-8")) - len(original.encode("utf-8"))
        return f"patched {path} ({replaced} replacement(s), {delta:+d} bytes)"


def _visible(text: str) -> str:
    return text.replace("\r", "␍").replace("\t", "→").replace(" ", "·")


def _match_lines(text: str, needle: str) -> list[int]:
    lines: list[int] = []
    start = 0
    step = max(len(needle), 1)
    while True:
        index = text.find(needle, start)
        if index < 0:
            return lines
        lines.append(text.count("\n", 0, index) + 1)
        start = index + step


def _mismatch_hints(original: str, old_str: str) -> str:
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
            notes.append(f"  {number}|{_visible(line)}")
        notes.append(f"  old|{_visible(needle)}")
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
            notes.append(f"  {number}|{_visible(candidate)}")
        notes.append(f"  old|{_visible(needle)}")
        return "\n".join(notes)

    notes.append("no similar lines found; re-read the file and copy the exact text")
    return "\n".join(notes)
