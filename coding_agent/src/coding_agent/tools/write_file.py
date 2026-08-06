"""Write a text file in the workspace."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

from pydantic import Field

from coding_agent.tools.base import ToolArgsModel, WorkspaceTool

if TYPE_CHECKING:
    from coding_agent.context.provider import RepositoryContextProvider


class WriteFileArgs(ToolArgsModel):
    path: str = Field(
        ...,
        min_length=1,
        description=(
            "Workspace-relative path to write "
            "(e.g. 'src/app.py'). Parent directories are created as needed."
        ),
    )
    content: str = Field(
        ...,
        description="Full UTF-8 text content to write. Overwrites the file if it exists.",
    )


class WriteFileTool(WorkspaceTool):
    name = "write_file"
    description = (
        "Create or overwrite a UTF-8 text file in the workspace. "
        "Creates missing parent directories. "
        "Returns a short confirmation with path and byte size. "
        "Paths are relative to the workspace root and cannot escape it."
    )
    args_model = WriteFileArgs

    def __init__(self, workspace: str | Path) -> None:
        super().__init__(workspace)
        self._context_provider: Optional["RepositoryContextProvider"] = None

    def bind_context_provider(self, provider: "RepositoryContextProvider") -> None:
        self._context_provider = provider

    def run(self, path: str, content: str) -> str:
        if not isinstance(content, str):
            return f"error: content must be a string, got {type(content).__name__}"

        try:
            target = self.resolve_path(path)
        except (TypeError, ValueError) as exc:
            return f"error: {exc}"

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            encoded = content.encode("utf-8")
            target.write_bytes(encoded)
        except OSError as exc:
            return f"error: failed to write {path}: {exc}"

        if self._context_provider is not None:
            try:
                self._context_provider.invalidate(path)
            except Exception:
                pass

        return f"wrote {path} ({len(encoded)} bytes)"
