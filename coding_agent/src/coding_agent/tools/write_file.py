"""Write a text file in the workspace."""

from __future__ import annotations


from pydantic import ConfigDict, Field, field_validator

from coding_agent.tools.base import ToolArgsModel, WorkspaceTool


class WriteFileArgs(ToolArgsModel):
    """File content is whitespace-significant; only the path is normalized."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    path: str = Field(..., min_length=1, description="Workspace-relative path to write.")
    content: str = Field(..., description="Complete whitespace-significant UTF-8 file content.")

    @field_validator("path")
    @classmethod
    def _strip_path_only(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("path must be a non-empty string")
        return stripped


class WriteFileTool(WorkspaceTool):
    name = "write_file"
    description = (
        "Create or overwrite a UTF-8 text file inside the workspace while preserving "
        "content exactly, including indentation and final newlines."
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
