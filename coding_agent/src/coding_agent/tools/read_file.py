"""Read a text or image file."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from coding_agent.config import ReadFileConfig
from coding_agent.tools.base import ToolArgsModel, WorkspaceTool
from core_ai.content import image_part_from_bytes, sniff_image_media_type

DEFAULT_READ_FILE_CONFIG = ReadFileConfig()


class ReadFileArgs(ToolArgsModel):
    path: str = Field(
        ...,
        min_length=1,
        description=(
            "Path to a UTF-8 text file or image (png, jpeg, gif, webp, bmp, tiff). "
            "Relative paths start at the working directory; absolute and ~ paths are allowed."
        ),
    )
    offset: int = Field(
        default=1,
        ge=1,
        description=(
            "1-based line number to start reading from. Use to page "
            "through large text files (e.g. offset=501 to read past the cap). "
            "Ignored for images."
        ),
    )
    limit: int = Field(
        default=0,
        ge=0,
        description=(
            "Maximum number of lines to return. 0 means no line cap; "
            "the byte cap still applies. Ignored for images."
        ),
    )


class ReadFileTool(WorkspaceTool):
    name = "read_file"
    description = (
        "Read a file. UTF-8 text is returned with line numbers "
        "(`   12|code`, capped at ~32KB; pass offset to page). Images (png, jpeg, "
        "gif, webp, bmp, tiff) are returned as visual content the model can see. "
        "Relative paths start at the working directory; absolute and ~ paths are allowed."
    )
    args_model = ReadFileArgs

    def __init__(
        self,
        workspace: str | Path,
        *,
        config: ReadFileConfig = DEFAULT_READ_FILE_CONFIG,
    ) -> None:
        self.config = config
        super().__init__(workspace)

    def run(
        self, path: str, offset: int = 1, limit: int = 0
    ) -> str | list[dict[str, object]]:
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
            size = target.stat().st_size
            with target.open("rb") as handle:
                header = handle.read(32)
        except OSError as exc:
            return f"error: failed to read {path}: {exc}"

        media_type = sniff_image_media_type(header, filename=target.name)
        if media_type:
            return self.read_image(target, path, media_type, size)
        return self.read_text(target, path, offset, limit)

    def read_image(
        self,
        target: Path,
        path: str,
        media_type: str,
        size: int,
    ) -> str | list[dict[str, object]]:
        if size > self.config.max_image_bytes:
            return (
                f"error: image exceeds {self.config.max_image_bytes:,} bytes: {path} "
                f"({size:,} bytes)"
            )
        try:
            payload = target.read_bytes()
        except OSError as exc:
            return f"error: failed to read {path}: {exc}"
        media_type = sniff_image_media_type(payload, filename=target.name) or media_type
        return [
            {
                "type": "text",
                "text": f"Read image {path} ({media_type}, {size:,} bytes)",
            },
            image_part_from_bytes(
                payload,
                media_type=media_type,
                filename=target.name,
            ),
        ]

    def read_text(self, target: Path, path: str, offset: int, limit: int) -> str:
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
                    if bytes_read + len(encoded) > self.config.max_text_bytes:
                        truncated = True
                        break
                    lines.append(line)
                    bytes_read += len(encoded)
                    collected += 1
        except UnicodeDecodeError:
            return f"error: file is not valid UTF-8 text: {path}"
        except OSError as exc:
            return f"error: failed to read {path}: {exc}"

        text = numbered_text(lines, offset)
        if truncated:
            text += (
                f"\n<output truncated at {bytes_read} bytes; "
                f"read again with offset={offset + collected} to continue>"
            )
        return text


def numbered_text(lines: list[str], start: int) -> str:
    if not lines:
        return ""
    last = start + len(lines) - 1
    width = max(4, len(str(last)))
    rendered: list[str] = []
    for index, line in enumerate(lines):
        body = line[:-1] if line.endswith("\n") else line
        rendered.append(f"{start + index:>{width}}|{body}")
    text = "\n".join(rendered)
    if lines[-1].endswith("\n"):
        text += "\n"
    return text
