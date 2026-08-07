"""Unified workspace search for file names and text content."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from pydantic import Field

from coding_agent.tools.base import ToolArgsModel, WorkspaceTool
from coding_agent.utils.ignore_file import DEFAULT_SKIP_DIRS, is_ignored

DEFAULT_MAX_RESULTS = 100
DEFAULT_MAX_LINE_CHARS = 240
BINARY_SNIFF_BYTES = 8192


class SearchArgs(ToolArgsModel):
    query: str = Field(..., min_length=1, description="Text or regular expression to search for.")
    mode: str = Field(default="content", description="Search mode: 'content' or 'files'.")
    path: str = Field(default=".", description="Workspace-relative file or directory to search.")
    glob: str = Field(default="", description="Optional file glob, for example '*.py'.")
    regex: bool = Field(default=False, description="Interpret query as a regular expression.")
    case_insensitive: bool = Field(default=False, description="Match without regard to case.")
    max_results: int = Field(default=DEFAULT_MAX_RESULTS, ge=1, le=500)
    max_line_chars: int = Field(default=DEFAULT_MAX_LINE_CHARS, ge=1, le=1000)


class SearchTool(WorkspaceTool):
    name = "search"
    description = (
        "Search workspace file names or text content. Returns file paths for mode=files "
        "and path:line:content for mode=content. Supports literal or regex queries, "
        "path/glob scoping, case-insensitive matching, and bounded output."
    )
    args_model = SearchArgs

    def run(
        self,
        query: str,
        mode: str = "content",
        path: str = ".",
        glob: str = "",
        regex: bool = False,
        case_insensitive: bool = False,
        max_results: int = DEFAULT_MAX_RESULTS,
        max_line_chars: int = DEFAULT_MAX_LINE_CHARS,
    ) -> str:
        mode = mode.strip().lower()
        if mode not in {"content", "files"}:
            return "error: mode must be 'content' or 'files'"
        try:
            root = self.resolve_path(path)
        except (TypeError, ValueError) as exc:
            return f"error: {exc}"
        if not root.exists():
            return f"error: path not found: {path}"

        flags = re.IGNORECASE if case_insensitive else 0
        try:
            matcher = re.compile(query if regex else re.escape(query), flags)
        except re.error as exc:
            return f"error: invalid regex: {exc}"

        limit = max(1, min(max_results, 500))
        line_cap = max(1, min(max_line_chars, 1000))
        results: list[str] = []
        files = list(self._iter_files(root, glob))

        if mode == "files":
            for file_path in files:
                relative = file_path.relative_to(self.workspace).as_posix()
                if matcher.search(relative):
                    results.append(relative)
                    if len(results) >= limit:
                        break
        else:
            for file_path in files:
                relative = file_path.relative_to(self.workspace).as_posix()
                for line_no, line in self._iter_text_lines(file_path):
                    if not matcher.search(line):
                        continue
                    content = line.rstrip()
                    if len(content) > line_cap:
                        content = content[:line_cap] + "…"
                    results.append(f"{relative}:{line_no}:{content}")
                    if len(results) >= limit:
                        break
                if len(results) >= limit:
                    break

        if not results:
            return f"no {mode} matches for {query!r}"
        suffix = " (capped)" if len(results) >= limit else ""
        return f"{len(results)} {mode} matches{suffix}\n" + "\n".join(results)

    def _iter_files(self, root: Path, glob_pattern: str):
        candidates = [root] if root.is_file() else sorted(root.rglob("*"))
        for candidate in candidates:
            if not candidate.is_file() or not self._searchable(candidate):
                continue
            relative = candidate.relative_to(self.workspace).as_posix()
            if glob_pattern and not (
                fnmatch.fnmatch(candidate.name, glob_pattern)
                or fnmatch.fnmatch(relative, glob_pattern)
            ):
                continue
            yield candidate

    def _searchable(self, path: Path) -> bool:
        relative_parts = path.relative_to(self.workspace).parts
        if any(part in DEFAULT_SKIP_DIRS for part in relative_parts):
            return False
        if any(part.startswith(".") for part in relative_parts):
            return False
        return not is_ignored(path, self.workspace)

    def _iter_text_lines(self, path: Path):
        try:
            sample = path.read_bytes()[:BINARY_SNIFF_BYTES]
            if b"\x00" in sample:
                return
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return
        for line_no, line in enumerate(text.splitlines(), start=1):
            yield line_no, line
