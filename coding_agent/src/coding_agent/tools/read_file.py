"""Read a text file from the workspace."""

from __future__ import annotations

from pydantic import Field

from coding_agent.tools.base import ToolArgsModel, WorkspaceTool


class ReadFileArgs(ToolArgsModel):
    path: str = Field(
        ...,
        min_length=1,
        description=(
            "Workspace-relative path to the UTF-8 text file to read "
            "(e.g. 'src/main.py')."
        ),
    )


class ReadFileTool(WorkspaceTool):
    name = "read_file"
    description = (
        "Read a UTF-8 text file from the workspace and return its full contents. "
        "Use for inspecting source, configs, and other text files. "
        "Paths are relative to the workspace root and cannot escape it."
    )
    args_model = ReadFileArgs

    def run(self, path: str) -> str:
        try:
            target = self.resolve_path(path)
        except (TypeError, ValueError) as exc:
            return f"error: {exc}"

        if not target.exists():
            return f"error: file not found: {path}"
        if not target.is_file():
            return f"error: not a file: {path}"
        try:
            return target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return f"error: file is not valid UTF-8 text: {path}"
        except OSError as exc:
            return f"error: failed to read {path}: {exc}"
