"""Surgical patch / edit-file tool for workspace text files."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

from pydantic import ConfigDict, Field, field_validator

from coding_agent.tools.base import ToolArgsModel, WorkspaceTool

if TYPE_CHECKING:
    from coding_agent.context.provider import RepositoryContextProvider


class PatchArgs(ToolArgsModel):
    """Patch args must preserve exact whitespace in old_str/new_str."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    path: str = Field(
        ...,
        min_length=1,
        description=(
            "Workspace-relative path to edit "
            "(e.g. 'src/app.py'). File must already exist."
        ),
    )
    old_str: str = Field(
        ...,
        min_length=1,
        description=(
            "Exact text to find in the file (whitespace-significant). "
            "Must match uniquely unless replace_all is true."
        ),
    )
    new_str: str = Field(
        ...,
        description=(
            "Replacement text for old_str (whitespace-significant). "
            "May be empty to delete the matched text."
        ),
    )
    replace_all: bool = Field(
        default=False,
        description="If true, replace every occurrence of old_str; otherwise require exactly one match.",
    )

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
        "Surgically edit an existing UTF-8 text file by replacing exact text. "
        "Prefer this over write_file when changing part of a file. "
        "old_str must match the file contents exactly (including whitespace). "
        "Returns a short confirmation with match count, or an error."
    )
    args_model = PatchArgs

    def __init__(self, workspace: str | Path) -> None:
        super().__init__(workspace)
        self._context_provider: Optional["RepositoryContextProvider"] = None

    def bind_context_provider(self, provider: "RepositoryContextProvider") -> None:
        self._context_provider = provider

    def run(
        self,
        path: str,
        old_str: str,
        new_str: str,
        replace_all: bool = False,
    ) -> str:
        if old_str == new_str:
            return "error: old_str and new_str are identical; nothing to change"

        try:
            target = self.resolve_path(path)
        except (TypeError, ValueError) as exc:
            return f"error: {exc}"

        try:
            if target.is_symlink():
                resolved = target.resolve()
                if not resolved.is_relative_to(self.workspace):
                    return f"error: Path escapes workspace: {path}"
        except OSError as exc:
            return f"error: failed to resolve {path}: {exc}"

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
            return (
                "error: old_str not found in file. "
                "Re-read the file and copy the exact text to replace."
            )
        if count > 1 and not replace_all:
            return (
                f"error: old_str matched {count} times; "
                "provide more context for a unique match or set replace_all=true"
            )

        if replace_all:
            updated = original.replace(old_str, new_str)
            replaced = count
        else:
            updated = original.replace(old_str, new_str, 1)
            replaced = 1

        try:
            target.write_text(updated, encoding="utf-8")
        except OSError as exc:
            return f"error: failed to write {path}: {exc}"

        if self._context_provider is not None:
            try:
                self._context_provider.invalidate(path)
            except Exception:
                pass

        delta = len(updated.encode("utf-8")) - len(original.encode("utf-8"))
        sign = "+" if delta >= 0 else ""
        return f"patched {path} ({replaced} replacement(s), {sign}{delta} bytes)"
