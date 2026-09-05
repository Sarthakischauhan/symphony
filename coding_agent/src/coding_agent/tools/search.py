"""Unified workspace search for file names and text content."""

from __future__ import annotations

import fnmatch
import re
from functools import lru_cache
from pathlib import Path

from pydantic import Field

from coding_agent.config import SearchConfig
from coding_agent.tools.base import ToolArgsModel, WorkspaceTool

DEFAULT_SKIP_DIRS = {
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

Rule = tuple[re.Pattern, bool, bool]  # (regex, dir_only, negated)


def glob_to_regex(pattern: str) -> str:
    """Convert a gitignore-style glob into a regex fragment.

    ``*`` matches within a path segment, ``**`` crosses segments, and
    ``?`` matches one non-slash character.
    """
    i = 0
    n = len(pattern)
    out: list[str] = []
    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                out.append(".*")
                i += 2
            else:
                out.append("[^/]*")
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return "".join(out)


def parse_line(line: str) -> Rule | None:
    """Parse one gitignore line into a rule, or None to skip it.

    Supports the common subset: blank lines, ``#`` comments, ``!``
    negation, trailing ``/`` for directory-only rules, and ``/``-anchored
    patterns. Last matching rule wins.
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    negated = False
    if line.startswith("!"):
        negated = True
        line = line[1:].strip()
    if not line:
        return None
    dir_only = line.endswith("/")
    if dir_only:
        line = line.rstrip("/")
    anchored = line.startswith("/")
    line = line.lstrip("/")
    if anchored or "/" in line:
        regex = re.compile(glob_to_regex(line))
    else:
        regex = re.compile(r"(?:.*/)?" + glob_to_regex(line))
    return regex, dir_only, negated


def is_matched(rules: tuple[Rule, ...], rel_path: str, is_dir: bool) -> bool | None:
    """Last matching rule's ignore status, or None if no rule matched."""
    result = None
    for regex, dir_only, negated in rules:
        if dir_only and not is_dir:
            continue
        if regex.fullmatch(rel_path):
            result = not negated
    return result


def rel_ignored(rules: tuple[Rule, ...], rel_path: str) -> bool:
    """Whether ``rel_path`` (posix) is ignored, checking each ancestor dir."""
    if rel_path in (".", ""):
        return False
    parts = rel_path.split("/")
    ignored = False
    for i in range(1, len(parts) + 1):
        candidate = "/".join(parts[:i])
        m = is_matched(rules, candidate, i < len(parts))
        if m is True:
            ignored = True
        elif m is False and not ignored:
            ignored = False
    return ignored


@lru_cache(maxsize=128)
def load_rules(
    workspace: Path,
) -> tuple[tuple[Path, tuple[Rule, ...]], ...]:
    """Parse every .gitignore under the workspace, keyed by its parent dir."""
    matchers: list[tuple[Path, tuple[Rule, ...]]] = []
    if not workspace.exists():
        return tuple(matchers)
    for gif in workspace.rglob(".gitignore"):
        if any(part in DEFAULT_SKIP_DIRS for part in gif.parts):
            continue
        try:
            rules = tuple(filter(None, (parse_line(line) for line in gif.read_text(encoding="utf-8").splitlines())))
        except (OSError, UnicodeDecodeError):
            continue
        matchers.append((gif.parent, rules))
    return tuple(matchers)


def is_ignored(path: Path, workspace: Path) -> bool:
    """Whether ``path`` is matched by a .gitignore under ``workspace``."""
    for base, rules in load_rules(workspace):
        if path.is_relative_to(base) and rel_ignored(rules, path.relative_to(base).as_posix()):
            return True
    return False


DEFAULT_SEARCH_CONFIG = SearchConfig()


class SearchArgs(ToolArgsModel):
    query: str = Field(..., min_length=1, description="Text or regular expression to search for.")
    mode: str = Field(default="content", description="Search mode: 'content' or 'files'.")
    path: str = Field(default=".", description="Workspace-relative file or directory to search.")
    glob: str = Field(default="", description="Optional file glob, for example '*.py'.")
    regex: bool = Field(default=False, description="Interpret query as a regular expression.")
    case_insensitive: bool = Field(default=False, description="Match without regard to case.")
    max_results: int = Field(default=DEFAULT_SEARCH_CONFIG.default_max_results, ge=1)
    max_line_chars: int = Field(default=DEFAULT_SEARCH_CONFIG.default_max_line_chars, ge=1)


class SearchTool(WorkspaceTool):
    name = "search"
    description = (
        "Search workspace file names or text content. Returns file paths for mode=files "
        "and path:line:content for mode=content. Supports literal or regex queries, "
        "path/glob scoping, case-insensitive matching, and bounded output."
    )
    args_model = SearchArgs

    def __init__(
        self,
        workspace: str | Path,
        *,
        config: SearchConfig = DEFAULT_SEARCH_CONFIG,
    ) -> None:
        self.config = config
        super().__init__(workspace)
        properties = self.parameters["properties"]
        properties["max_results"]["default"] = config.default_max_results
        properties["max_line_chars"]["default"] = config.default_max_line_chars

    def prepare_args(self, args: dict[str, object]) -> dict[str, object]:
        prepared = dict(args)
        prepared.setdefault("max_results", self.config.default_max_results)
        prepared.setdefault("max_line_chars", self.config.default_max_line_chars)
        return prepared

    def run(
        self,
        query: str,
        mode: str = "content",
        path: str = ".",
        glob: str = "",
        regex: bool = False,
        case_insensitive: bool = False,
        max_results: int = DEFAULT_SEARCH_CONFIG.default_max_results,
        max_line_chars: int = DEFAULT_SEARCH_CONFIG.default_max_line_chars,
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

        limit = max(1, max_results)
        line_cap = max(1, max_line_chars)
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
            sample = path.read_bytes()[: self.config.binary_sniff_bytes]
            if b"\x00" in sample:
                return
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return
        for line_no, line in enumerate(text.splitlines(), start=1):
            yield line_no, line
