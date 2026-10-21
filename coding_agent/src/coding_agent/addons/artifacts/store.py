"""Versioned artifact files under ``<session dir>/artifacts``.

Layout, per session::

    artifacts/index.json                  every artifact's latest manifest
    artifacts/<artifact_id>/manifest.json the latest version's manifest
    artifacts/<artifact_id>/v<N>/...      the files of version N

A version directory is staged under a temporary name and renamed into place,
and both JSON files are published with a temporary file plus rename, so a
reader never sees a partial artifact. The id is derived from the kind and the
source path, so later writes of the same file or site are versions of one
artifact. A snapshot whose sha256 matches the latest version stores nothing.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from coding_agent.addons.artifacts.capture import Snapshot
from coding_agent.addons.artifacts.kinds import ArtifactKind
from coding_agent.addons.persistence.artifacts import safe_path, snapshot

SESSION_ID = re.compile(r"^[A-Za-z0-9._-]+$")
ARTIFACT_ID = re.compile(r"^[0-9a-f]{16}$")
INDEX = "index.json"
MANIFEST = "manifest.json"


@dataclass(frozen=True)
class Manifest:
    """One artifact's latest version. ``entry`` is relative to the artifact folder."""

    id: str
    kind: ArtifactKind
    title: str
    created_at: str
    updated_at: str
    version: int
    tool_call_id: str
    source: str
    entry: str
    mime: str
    sha256: str
    size: int

    def to_json(self) -> dict[str, object]:
        return {**asdict(self), "kind": self.kind.value}

    @classmethod
    def from_json(cls, data: dict[str, object]) -> Manifest:
        def text(key: str) -> str:
            value = data.get(key)
            if not isinstance(value, str):
                raise ValueError(f"artifact manifest field {key!r} must be a string")
            return value

        def number(key: str) -> int:
            value = data.get(key)
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"artifact manifest field {key!r} must be an integer")
            return value

        return cls(
            id=text("id"), kind=ArtifactKind(text("kind")), title=text("title"),
            created_at=text("created_at"), updated_at=text("updated_at"), version=number("version"),
            tool_call_id=text("tool_call_id"), source=text("source"), entry=text("entry"),
            mime=text("mime"), sha256=text("sha256"), size=number("size"),
        )


@dataclass(frozen=True)
class Saved:
    """A stored version. ``created`` is false when it updated an existing artifact."""

    manifest: Manifest
    created: bool


def artifact_id(kind: ArtifactKind, source: str) -> str:
    return hashlib.sha256(f"{kind.value}:{source}".encode()).hexdigest()[:16]


def content_digest(files: tuple[tuple[str, bytes], ...]) -> str:
    """sha256 of one file's bytes, or of a folder's sorted (path, file sha256) list."""
    if len(files) == 1:
        return hashlib.sha256(files[0][1]).hexdigest()
    listing = "".join(f"{name}\0{hashlib.sha256(payload).hexdigest()}\n" for name, payload in sorted(files))
    return hashlib.sha256(listing.encode()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> dict[str, object] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if not isinstance(data, dict):
        raise ValueError(f"not a JSON object: {path}")
    return data


class ArtifactStore:
    """Artifacts of the sessions under one sessions directory."""

    def __init__(self, sessions_root: Path) -> None:
        self.sessions_root = Path(sessions_root).expanduser().resolve()
        self._lock = threading.Lock()

    def directory(self, session_id: str) -> Path:
        if session_id in {".", ".."} or not SESSION_ID.fullmatch(session_id):
            raise ValueError(f"invalid session_id: {session_id!r}")
        return safe_path(self.sessions_root, session_id, "artifacts")

    def folder(self, session_id: str, artifact: str) -> Path:
        if not ARTIFACT_ID.fullmatch(artifact):
            raise ValueError(f"invalid artifact_id: {artifact!r}")
        return safe_path(self.directory(session_id), artifact)

    def save(self, session_id: str, captured: Snapshot, tool_call_id: str) -> Saved | None:
        """Store ``captured`` as a new version; ``None`` when its content is unchanged."""
        identifier = artifact_id(captured.kind, captured.source)
        digest = content_digest(captured.files)
        with self._lock:
            folder = self.folder(session_id, identifier)
            stored = _read_json(folder / MANIFEST)
            previous = Manifest.from_json(stored) if stored is not None else None
            if previous is not None and previous.sha256 == digest:
                return None
            version = previous.version + 1 if previous is not None else 1
            self._write_version(folder, f"v{version}", captured.files)
            now = _now()
            manifest = Manifest(
                id=identifier,
                kind=captured.kind,
                title=captured.title,
                created_at=previous.created_at if previous is not None else now,
                updated_at=now,
                version=version,
                tool_call_id=tool_call_id,
                source=captured.source,
                entry=f"v{version}/{captured.entry}",
                mime=captured.mime,
                sha256=digest,
                size=sum(len(payload) for _, payload in captured.files),
            )
            snapshot(folder / MANIFEST, manifest.to_json())
            self._index(session_id, manifest)
            return Saved(manifest=manifest, created=previous is None)

    def _write_version(self, folder: Path, name: str, files: tuple[tuple[str, bytes], ...]) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        staging = safe_path(folder, f".{name}.{uuid.uuid4().hex}.tmp")
        try:
            for relative, payload in files:
                target = safe_path(staging, *relative.split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
            final = safe_path(folder, name)
            if final.exists():
                # Left by a save that crashed before its manifest was published.
                shutil.rmtree(final)
            staging.rename(final)
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def _index(self, session_id: str, manifest: Manifest) -> None:
        rows = [row for row in self.manifests(session_id) if row.id != manifest.id]
        rows.append(manifest)
        snapshot(self.directory(session_id) / INDEX, {"artifacts": [row.to_json() for row in rows]})

    def manifests(self, session_id: str) -> list[Manifest]:
        """Every artifact of the session in creation order; empty before the first."""
        data = _read_json(self.directory(session_id) / INDEX)
        rows = data.get("artifacts") if data is not None else []
        if not isinstance(rows, list):
            raise ValueError("artifact index must hold a list")
        return [Manifest.from_json(row) for row in rows if isinstance(row, dict)]

    def get(self, session_id: str, artifact: str) -> Manifest:
        stored = _read_json(self.folder(session_id, artifact) / MANIFEST)
        if stored is None:
            raise KeyError(f"unknown artifact: {artifact}")
        return Manifest.from_json(stored)

    def file(self, session_id: str, artifact: str, relative: str) -> Path:
        """A stored file of the artifact; rejects traversal, links and folders."""
        parts = [part for part in relative.split("/") if part]
        path = safe_path(self.folder(session_id, artifact), *parts)
        if not parts or not path.is_file():
            raise KeyError(f"no such artifact file: {relative}")
        return path

    def files(self, session_id: str, manifest: Manifest) -> list[str]:
        """The latest version's files, relative to its version folder."""
        version = safe_path(self.folder(session_id, manifest.id), f"v{manifest.version}")
        return sorted(path.relative_to(version).as_posix() for path in version.rglob("*") if path.is_file())


__all__ = ["ArtifactStore", "Manifest", "Saved", "artifact_id", "content_digest"]
