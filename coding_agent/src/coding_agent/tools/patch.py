"""Surgical exact-text editing for workspace files."""

from __future__ import annotations

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
    description = "Replace exact text in an existing UTF-8 file; whitespace is significant."
    args_model = PatchArgs

    def run(self, path: str, old_str: str, new_str: str, replace_all: bool = False) -> str:
        if old_str == new_str:
            return "error: old_str and new_str are identical; nothing to change"
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

        count = original.count(old_str)
        if count == 0:
            return "error: old_str not found in file; re-read and copy the exact text"
        if count > 1 and not replace_all:
            return f"error: old_str matched {count} times; add context or set replace_all=true"
        updated = original.replace(old_str, new_str) if replace_all else original.replace(old_str, new_str, 1)
        try:
            target.write_text(updated, encoding="utf-8")
        except OSError as exc:
            return f"error: failed to write {path}: {exc}"
        replaced = count if replace_all else 1
        delta = len(updated.encode("utf-8")) - len(original.encode("utf-8"))
        return f"patched {path} ({replaced} replacement(s), {delta:+d} bytes)"
