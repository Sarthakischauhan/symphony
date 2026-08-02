"""Read a text file from the workspace."""

from __future__ import annotations

from pydantic import Field

from coding_agent.tools.base import ToolArgsModel, WorkspaceTool

MAX_READ_BYTES = 32_000
"""Hard cap on returned file content so a huge file can't flood model context."""


class ReadFileArgs(ToolArgsModel):
    path: str = Field(
        ...,
        min_length=1,
        description=(
            "Workspace-relative path to the UTF-8 text file to read "
            "(e.g. 'src/main.py')."
        ),
    )
    offset: int = Field(
        default=1,
        ge=1,
        description=(
            "1-based line number to start reading from. Use to page "
            "through large files (e.g. offset=501 to read past the cap)."
        ),
    )
    limit: int = Field(
        default=0,
        ge=0,
        description=(
            "Maximum number of lines to return. 0 means no line cap; "
            "the byte cap still applies."
        ),
    )


class ReadFileTool(WorkspaceTool):
    name = "read_file"
    description = (
        "Read a UTF-8 text file from the workspace and return its contents. "
        "Use for inspecting source, configs, and other text files. "
        "Large files are truncated at ~32KB; pass offset to page through "
        "the rest. Paths are relative to the workspace root and cannot escape it."
    )
    args_model = ReadFileArgs

    def run(self, path: str, offset: int = 1, limit: int = 0) -> str:
        try:
            target = self.resolve_path(path)
        except (TypeError, ValueError) as exc:
            return f"error: {exc}"

        if not isinstance(offset, int) or offset < 1:
            return "error: offset must be an integer >= 1"
        if not isinstance(limit, int) or limit < 0:
            return "error: limit must be an integer >= 0"

        if not target.exists():
            return f"error: file not found: {path}"
        if not target.is_file():
            return f"error: not a file: {path}"

        try:
            with target.open("r", encoding="utf-8") as fh:
                lines: list[str] = []
                bytes_read = 0
                collected = 0
                truncated = False
                for line_no, line in enumerate(fh, start=1):
                    if line_no < offset:
                        continue
                    if limit and collected >= limit:
                        break
                    encoded = line.encode("utf-8")
                    if bytes_read + len(encoded) > MAX_READ_BYTES:
                        truncated = True
                        break
                    lines.append(line)
                    bytes_read += len(encoded)
                    collected += 1
        except UnicodeDecodeError:
            return f"error: file is not valid UTF-8 text: {path}"
        except OSError as exc:
            return f"error: failed to read {path}: {exc}"

        text = "".join(lines)
        if truncated:
            text += (
                f"\n<output truncated at {bytes_read} bytes; "
                f"read again with offset={offset + collected} to continue>"
            )
        return text
