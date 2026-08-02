"""Search file contents in the workspace (grep)."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import Field

from coding_agent.tools.base import ToolArgsModel, WorkspaceTool
from coding_agent.utils.ignore_file import DEFAULT_SKIP_DIRS, is_ignored

DEFAULT_MAX_MATCHES = 100
BINARY_SNIFF_BYTES = 8192
DEFAULT_MAX_LINE_CHARS = 240
LINE_TRUNC_SUFFIX = "…"


class GrepArgs(ToolArgsModel):
    pattern: str = Field(
        ...,
        min_length=1,
        description="Regular expression to search for in file contents.",
    )
    path: str = Field(
        default=".",
        description=(
            "Workspace-relative file or directory to search. "
            "Defaults to the workspace root ('.')."
        ),
    )
    glob: str = Field(
        default="",
        description=(
            "Optional filename glob to filter files "
            "(e.g. '*.py', 'src/**/*.ts'). Empty means all files."
        ),
    )
    case_insensitive: bool = Field(
        default=False,
        description="When true, match pattern without regard to case.",
    )
    max_matches: int = Field(
        default=DEFAULT_MAX_MATCHES,
        ge=1,
        le=500,
        description="Maximum number of matching lines to return (1-500).",
    )
    include_ignored: bool = Field(
        default=False,
        description=(
            "When true, also search files matched by .gitignore rules "
            "and hidden/untracked paths. Defaults to skipping them."
        ),
    )
    max_line_chars: int = Field(
        default=DEFAULT_MAX_LINE_CHARS,
        ge=1,
        le=1000,
        description="Maximum characters of each matching line to return; longer lines are truncated.",
    )


class GrepTool(WorkspaceTool):
    name = "grep"
    description = (
        "Search workspace files for a regular expression and return matching lines "
        "as path:line:content. Optional path scopes the search to a file or directory. "
        "Optional glob filters filenames (e.g. '*.py'). Results are capped by max_matches "
        "and long lines are truncated. Honors .gitignore (unless include_ignored is set) "
        "and always skips common dependency and VCS directories."
    )
    args_model = GrepArgs

    def run(
        self,
        pattern: str,
        path: str = ".",
        glob: str = "",
        case_insensitive: bool = False,
        max_matches: int = DEFAULT_MAX_MATCHES,
        include_ignored: bool = False,
        max_line_chars: int = DEFAULT_MAX_LINE_CHARS,
    ) -> str:
        if not isinstance(pattern, str) or not pattern:
            return "error: pattern must be a non-empty string"
        if not isinstance(path, str):
            return f"error: path must be a string, got {type(path).__name__}"
        if not isinstance(glob, str):
            return f"error: glob must be a string, got {type(glob).__name__}"
        if not isinstance(case_insensitive, bool):
            return (
                "error: case_insensitive must be a boolean, "
                f"got {type(case_insensitive).__name__}"
            )
        if not isinstance(max_matches, int):
            return f"error: max_matches must be an int, got {type(max_matches).__name__}"
        if not isinstance(include_ignored, bool):
            return (
                "error: include_ignored must be a boolean, "
                f"got {type(include_ignored).__name__}"
            )
        if not isinstance(max_line_chars, int):
            return f"error: max_line_chars must be an int, got {type(max_line_chars).__name__}"

        try:
            flags = re.IGNORECASE if case_insensitive else 0
            regex = re.compile(pattern, flags)
        except re.error as exc:
            return f"error: invalid regex: {exc}"

        try:
            root = self.resolve_path(path)
        except (TypeError, ValueError) as exc:
            return f"error: {exc}"

        if not root.exists():
            return f"error: path not found: {path}"

        limit = max(1, min(max_matches, 500))
        line_cap = max(1, min(max_line_chars, 1000))
        matches: list[str] = []
        files_searched = 0

        for file_path in self._iter_files(root, glob, include_ignored):
            files_searched += 1
            for line_no, line in self._iter_text_lines(file_path):
                if regex.search(line):
                    rel = file_path.relative_to(self.workspace).as_posix()
                    content = self._truncate_line(line, line_cap)
                    matches.append(f"{rel}:{line_no}:{content}")
                    if len(matches) >= limit:
                        header = (
                            f"Showing {len(matches)} matches (capped) "
                            f"in {files_searched} files"
                        )
                        return header + "\n" + "\n".join(matches)

        if not matches:
            return f"no matches for {pattern!r} (searched {files_searched} files)"

        header = f"{len(matches)} matches in {files_searched} files"
        return header + "\n" + "\n".join(matches)

    def _iter_files(self, root: Path, glob_pattern: str, include_ignored: bool):
        if root.is_file():
            if self._should_search(root, include_ignored):
                yield root
            return

        pattern = glob_pattern.strip() or "*"
        for path in sorted(root.rglob(pattern)):
            if not path.is_file():
                continue
            if self._should_search(path, include_ignored):
                yield path

    def _should_search(self, path: Path, include_ignored: bool) -> bool:
        if any(part in DEFAULT_SKIP_DIRS for part in path.parts):
            return False
        if include_ignored:
            return True
        if any(part.startswith(".") for part in path.parts):
            return False
        return not is_ignored(path, self.workspace)

    def _truncate_line(self, line: str, line_cap: int) -> str:
        stripped = line.rstrip()
        if len(stripped) > line_cap:
            return stripped[:line_cap] + LINE_TRUNC_SUFFIX
        return stripped

    def _iter_text_lines(self, path: Path):
        try:
            sample = path.read_bytes()[:BINARY_SNIFF_BYTES]
        except OSError:
            return
        if b"\x00" in sample:
            return
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return
        for line_no, line in enumerate(text.splitlines(), start=1):
            yield line_no, line
