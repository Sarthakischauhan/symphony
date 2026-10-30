"""Write a text file in the workspace."""

from __future__ import annotations


from pydantic import ConfigDict, Field

from coding_agent.tools.base import NonEmptyPath, ToolArgsModel, WorkspaceTool


class WriteFileArgs(ToolArgsModel):
    """File content is whitespace-significant; only the path is normalized."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    path: NonEmptyPath = Field(
        ...,
        min_length=1,
        description="Path to write. Relative paths start at the working directory.",
    )
    content: str = Field(..., description="Complete whitespace-significant UTF-8 file content.")


class WriteFileTool(WorkspaceTool):
    name = "write_file"
    description = (
        "Create a file or replace its entire contents. Content is written unchanged, "
        "including indentation and the final newline. Use patch to change part of "
        "an existing file. Relative paths start at the working directory."
    )
    args_model = WriteFileArgs

    def run(self, path: str, content: str) -> str:
        try:
            target = self.resolve_path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            encoded = content.encode("utf-8")
            target.write_bytes(encoded)
        except (TypeError, ValueError, OSError) as exc:
            return f"error: failed to write {path}: {exc}"
        return f"wrote {path} ({len(encoded)} bytes)"
