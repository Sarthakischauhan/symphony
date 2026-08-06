"""Cached repository context shared by prompts and ast_query."""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Iterable, Optional

from coding_agent.ast.models import CodebaseSummary, ModuleSummary
from coding_agent.ast.semantic import SemanticIndex, build_semantic_index, query_semantic
from coding_agent.context.python_indexer import PythonAstIndexer
from coding_agent.context.types import FileFingerprint, IndexedFile, RepositoryIndexer
from coding_agent.utils.ignore_file import DEFAULT_SKIP_DIRS

DEFAULT_MAP_CHARS = 2500


class RepositoryContextProvider:
    """Incremental, hash/mtime-cached repository index.

    The initial repo map is intentionally small and token-budgeted. Detailed
    symbol / caller / definition retrieval happens on demand via ``query``.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        indexer: Optional[RepositoryIndexer] = None,
        max_map_chars: int = DEFAULT_MAP_CHARS,
    ) -> None:
        self.root = Path(root).resolve()
        self.indexer = indexer or PythonAstIndexer()
        self.max_map_chars = max_map_chars
        self._lock = threading.RLock()
        self._files: dict[str, IndexedFile] = {}
        self._index: SemanticIndex | None = None
        self._parse_count = 0
        self._refresh_count = 0

    @property
    def parse_count(self) -> int:
        return self._parse_count

    @property
    def refresh_count(self) -> int:
        return self._refresh_count

    def workspace_revision(self) -> str:
        """Stable revision fingerprint over currently indexed files."""
        with self._lock:
            self.refresh()
            digest = hashlib.sha256()
            for path in sorted(self._files):
                entry = self._files[path]
                digest.update(path.encode("utf-8"))
                digest.update(entry.fingerprint.content_hash.encode("utf-8"))
            return digest.hexdigest()[:16]

    def refresh(self) -> None:
        """Re-index only files whose mtime/size/hash changed."""
        with self._lock:
            self._refresh_count += 1
            current_paths = set(self._iter_source_files())
            changed = False

            for relative in list(self._files):
                if relative not in current_paths:
                    del self._files[relative]
                    changed = True

            for relative in current_paths:
                absolute = self.root / relative
                fingerprint = self._fingerprint(absolute, relative)
                if fingerprint is None:
                    # Unreadable: keep a stub module with an error if missing.
                    if relative not in self._files:
                        self._files[relative] = IndexedFile(
                            fingerprint=FileFingerprint(
                                path=relative, mtime_ns=0, size=0, content_hash=""
                            ),
                            module=ModuleSummary(
                                path=relative,
                                errors=("unreadable file",),
                                language=self.indexer.language,
                            ),
                            language=self.indexer.language,
                        )
                        changed = True
                    continue

                cached = self._files.get(relative)
                if (
                    cached is not None
                    and cached.fingerprint.mtime_ns == fingerprint.mtime_ns
                    and cached.fingerprint.size == fingerprint.size
                    and cached.fingerprint.content_hash == fingerprint.content_hash
                ):
                    continue

                try:
                    source = absolute.read_text(encoding="utf-8")
                except UnicodeDecodeError as exc:
                    module = ModuleSummary(
                        path=relative,
                        errors=(f"unable to decode UTF-8: {exc}",),
                        language=self.indexer.language,
                    )
                except OSError as exc:
                    module = ModuleSummary(
                        path=relative,
                        errors=(f"unreadable: {exc}",),
                        language=self.indexer.language,
                    )
                else:
                    module = self.indexer.parse_file(path=relative, source=source)
                    self._parse_count += 1

                self._files[relative] = IndexedFile(
                    fingerprint=fingerprint,
                    module=module,
                    language=self.indexer.language,
                )
                changed = True

            if changed or self._index is None:
                modules = tuple(
                    self._files[path].module for path in sorted(self._files)
                )
                self._index = build_semantic_index(
                    CodebaseSummary(root=str(self.root), modules=modules)
                )

    def invalidate(self, path: str | None = None) -> None:
        """Drop one file (or the whole cache) so the next refresh reparses."""
        with self._lock:
            if path is None:
                self._files.clear()
                self._index = None
                return
            relative = path.replace("\\", "/").lstrip("./")
            self._files.pop(relative, None)
            self._index = None

    def summary(self) -> CodebaseSummary:
        with self._lock:
            self.refresh()
            modules = tuple(
                self._files[path].module for path in sorted(self._files)
            )
            return CodebaseSummary(root=str(self.root), modules=modules)

    def repo_map(self, *, max_chars: int | None = None) -> str:
        """Token-budgeted repository map for prompt injection."""
        with self._lock:
            self.refresh()
            budget = self.max_map_chars if max_chars is None else max_chars
            return self.summary().to_markdown(max_chars=budget)

    def query(self, *, action: str, name: str = "", path: str = "") -> str:
        with self._lock:
            self.refresh()
            assert self._index is not None
            return query_semantic(self._index, action=action, name=name, path=path)

    def index(self) -> SemanticIndex:
        with self._lock:
            self.refresh()
            assert self._index is not None
            return self._index

    def _iter_source_files(self) -> Iterable[str]:
        if not self.root.exists():
            return []
        if self.root.is_file():
            if self.root.suffix in self.indexer.extensions:
                return [self.root.name]
            return []

        found: list[str] = []
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix not in self.indexer.extensions:
                continue
            try:
                parts = path.relative_to(self.root).parts
            except ValueError:
                continue
            if any(part in DEFAULT_SKIP_DIRS or part == ".symphony" for part in parts):
                continue
            if any(part.startswith(".") for part in parts[:-1]):
                continue
            found.append(Path(*parts).as_posix())
        return found

    def _fingerprint(self, absolute: Path, relative: str) -> FileFingerprint | None:
        try:
            stat = absolute.stat()
            data = absolute.read_bytes()
        except OSError:
            return None
        digest = hashlib.sha256(data).hexdigest()
        return FileFingerprint(
            path=relative,
            mtime_ns=getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1e9)),
            size=stat.st_size,
            content_hash=digest,
        )
