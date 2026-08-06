"""Repository context protocols and shared types.

Designed so a Python-AST indexer can later be replaced by Tree-sitter or LSP
backends without changing prompt / tool call sites.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from coding_agent.ast.models import ModuleSummary


@dataclass(frozen=True)
class FileFingerprint:
    """Identity of a source file used for cache invalidation."""

    path: str
    mtime_ns: int
    size: int
    content_hash: str


@dataclass
class IndexedFile:
    """Cached parse result for one source file."""

    fingerprint: FileFingerprint
    module: ModuleSummary
    language: str = "python"


@runtime_checkable
class RepositoryIndexer(Protocol):
    """Pluggable language indexer (Python AST today; Tree-sitter/LSP later)."""

    language: str
    extensions: tuple[str, ...]

    def parse_file(
        self,
        *,
        path: str,
        source: str,
    ) -> ModuleSummary:
        """Parse one file into a ModuleSummary; never raise for bad source."""
        ...
