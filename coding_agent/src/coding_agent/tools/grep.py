"""Search file contents in the workspace (grep)."""

from __future__ import annotations

import re
from pathlib import Path

from coding_agent.tools.base import WorkspaceTool

DEFAULT_MAX_MATCHES = 100
BINARY_SNIFF_BYTES = 8192
SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".tox",
}


class GrepTool(WorkspaceTool):
    name = "grep"
    description = (
        "Search for a regex pattern in workspace files. "
        "Optional path scopes the search (file or directory). "
        "Optional glob filters filenames (e.g. '*.py'). "
        "Returns matching lines as path:line:content (capped)."
    )

    def run(
        self,
        pattern: str,
        path: str = ".",
        glob: str = "",
        case_insensitive: bool = False,
        max_matches: int = DEFAULT_MAX_MATCHES,
    ) -> str:
        """Search workspace files for a regex pattern."""
        try:
            flags = re.IGNORECASE if case_insensitive else 0
            regex = re.compile(pattern, flags)
        except re.error as exc:
            return f"error: invalid regex: {exc}"

        try:
            root = self.resolve_path(path)
        except ValueError as exc:
            return f"error: {exc}"

        if not root.exists():
            return f"error: path not found: {path}"

        limit = max(1, min(max_matches, 500))
        matches: list[str] = []
        files_searched = 0

        for file_path in self._iter_files(root, glob):
            files_searched += 1
            for line_no, line in self._iter_text_lines(file_path):
                if regex.search(line):
                    rel = file_path.relative_to(self.workspace).as_posix()
                    matches.append(f"{rel}:{line_no}:{line.rstrip()}")
                    if len(matches) >= limit:
                        header = f"Showing {len(matches)} matches (capped) in {files_searched} files"
                        return header + "\n" + "\n".join(matches)

        if not matches:
            return f"no matches for {pattern!r} (searched {files_searched} files)"

        header = f"{len(matches)} matches in {files_searched} files"
        return header + "\n" + "\n".join(matches)

    def _iter_files(self, root: Path, glob_pattern: str):
        if root.is_file():
            yield root
            return

        pattern = glob_pattern.strip() or "*"
        for path in sorted(root.rglob(pattern)):
            if not path.is_file():
                continue
            if any(part in SKIP_DIR_NAMES for part in path.parts):
                continue
            yield path

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
