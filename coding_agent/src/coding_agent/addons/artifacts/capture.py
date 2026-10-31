"""Turn a written path or an image result part into an artifact snapshot.

A snapshot is the complete content of one artifact version: its kind, a
stable source (the workspace path it came from), the entry file and every
file's bytes. ``ArtifactStore`` versions snapshots by sha256.

- An image (png/jpg/jpeg/webp/gif/svg), a ``.csv`` or a ``.json`` file is a
  single-file artifact. CSV must be UTF-8 and JSON must parse.
- A ``.html`` file is a single-file html artifact, except ``index.html`` in a
  folder below the workspace, which captures that whole folder (the site and
  its assets) with ``index.html`` as the entry.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from core_ai.content import sniff_image_media_type

from coding_agent.addons.artifacts.kinds import IMAGE_MIME_TYPES, TEXT_MIME_TYPES, ArtifactKind, kind_of
from coding_agent.addons.artifacts.noise import is_app_project

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_SITE_FILES = 200
MAX_SITE_BYTES = 20 * 1024 * 1024
SKIPPED_DIRS = frozenset({"node_modules", "__pycache__"})
SITE_ENTRY = "index.html"


class ArtifactError(ValueError):
    """The path cannot become an artifact of the requested kind."""


@dataclass(frozen=True)
class Snapshot:
    kind: ArtifactKind
    source: str
    title: str
    entry: str
    mime: str
    files: tuple[tuple[str, bytes], ...]


def display_source(path: Path, workspace: Path) -> str:
    """The path relative to the workspace when inside it, else absolute."""
    return path.relative_to(workspace).as_posix() if path.is_relative_to(workspace) else str(path)


def _read(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ArtifactError(f"not a regular file: {path}")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ArtifactError(f"file is over {MAX_FILE_BYTES // (1024 * 1024)} MiB: {path}")
    return path.read_bytes()


def image_mime(payload: bytes, name: str) -> str:
    """png/jpg/jpeg/webp/gif/svg by suffix, else by magic bytes."""
    suffix = Path(name).suffix.lower()
    if suffix in IMAGE_MIME_TYPES:
        return IMAGE_MIME_TYPES[suffix]
    sniffed = sniff_image_media_type(payload)
    if sniffed not in IMAGE_MIME_TYPES.values():
        raise ArtifactError(f"not a png, jpeg, webp, gif or svg image: {name}")
    return sniffed


def _check_text(kind: ArtifactKind, payload: bytes, name: str) -> None:
    try:
        text = payload.decode("utf-8")
        if kind is ArtifactKind.JSON:
            json.loads(text)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ArtifactError(f"{name} is not valid {kind.value}: {exc}") from exc


def _site_files(folder: Path) -> tuple[tuple[str, bytes], ...]:
    files: list[tuple[str, bytes]] = []
    total = 0
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(folder)
        if any(part.startswith(".") or part in SKIPPED_DIRS for part in relative.parts):
            continue
        if path.is_symlink() or not path.is_file():
            continue
        payload = _read(path)
        total += len(payload)
        files.append((relative.as_posix(), payload))
        if len(files) > MAX_SITE_FILES or total > MAX_SITE_BYTES:
            raise ArtifactError(f"site folder is too large to keep as an artifact: {folder}")
    return tuple(files)


def snapshot_site(folder: Path, workspace: Path, title: str = "") -> Snapshot:
    """A website folder whose entry is ``index.html``."""
    if not (folder / SITE_ENTRY).is_file():
        raise ArtifactError(f"a website folder needs {SITE_ENTRY}: {folder}")
    return Snapshot(
        kind=ArtifactKind.HTML,
        source=display_source(folder, workspace),
        title=title or folder.name,
        entry=SITE_ENTRY,
        mime=TEXT_MIME_TYPES[ArtifactKind.HTML],
        files=_site_files(folder),
    )


def snapshot_path(path: Path, workspace: Path, kind: ArtifactKind | None = None, title: str = "") -> Snapshot:
    """Snapshot a written file or folder; ``kind`` defaults to the suffix's kind."""
    if path.is_dir() and not path.is_symlink():
        if kind not in (None, ArtifactKind.HTML):
            raise ArtifactError(f"only an html artifact can be a folder: {path}")
        return snapshot_site(path, workspace, title)
    chosen = kind or kind_of(path)
    if chosen is None:
        raise ArtifactError(f"not an html, csv, json or image file: {path}")
    if (
        chosen is ArtifactKind.HTML
        and path.name == SITE_ENTRY
        and path.parent != workspace
        and not is_app_project(path.parent)
    ):
        return snapshot_site(path.parent, workspace, title)
    payload = _read(path)
    if chosen is ArtifactKind.IMAGE:
        mime = image_mime(payload, path.name)
    else:
        _check_text(chosen, payload, path.name)
        mime = TEXT_MIME_TYPES[chosen]
    return Snapshot(
        kind=chosen,
        source=display_source(path, workspace),
        title=title or path.name,
        entry=path.name,
        mime=mime,
        files=((path.name, payload),),
    )


def snapshot_image_part(part: Mapping[str, object], call_id: str, index: int) -> Snapshot | None:
    """An inline image a tool returned without writing a file."""
    data = part.get("data")
    if part.get("type") != "image" or not isinstance(data, str):
        return None
    try:
        payload = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        return None
    filename = part.get("filename")
    name = Path(filename).name if isinstance(filename, str) and Path(filename).name else f"image-{index + 1}"
    try:
        mime = image_mime(payload, name)
    except ArtifactError:
        return None
    suffix = next(key for key, value in IMAGE_MIME_TYPES.items() if value == mime)
    entry = name if Path(name).suffix.lower() in IMAGE_MIME_TYPES else f"{name}{suffix}"
    return Snapshot(
        kind=ArtifactKind.IMAGE,
        source=f"{call_id}#image-{index + 1}",
        title=name,
        entry=entry,
        mime=mime,
        files=((entry, payload),),
    )


__all__ = [
    "ArtifactError", "MAX_FILE_BYTES", "MAX_SITE_BYTES", "MAX_SITE_FILES", "SITE_ENTRY", "Snapshot",
    "display_source", "image_mime", "snapshot_image_part", "snapshot_path", "snapshot_site",
]
