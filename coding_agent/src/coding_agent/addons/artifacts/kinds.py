"""The four artifact kinds and the file suffixes that map to them."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path


class ArtifactKind(StrEnum):
    """What an artifact holds. Hosts pick a preview from this."""

    HTML = "html"
    CSV = "csv"
    JSON = "json"
    IMAGE = "image"


IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
}
TEXT_MIME_TYPES = {
    ArtifactKind.HTML: "text/html",
    ArtifactKind.CSV: "text/csv",
    ArtifactKind.JSON: "application/json",
}
SUFFIX_KINDS = {
    ".html": ArtifactKind.HTML,
    ".csv": ArtifactKind.CSV,
    ".json": ArtifactKind.JSON,
    **{suffix: ArtifactKind.IMAGE for suffix in IMAGE_MIME_TYPES},
}


def kind_of(path: Path) -> ArtifactKind | None:
    """The kind auto-capture assigns to ``path``, or ``None`` for other files."""
    return SUFFIX_KINDS.get(path.suffix.lower())


def mime_of(kind: ArtifactKind, entry: Path) -> str:
    """The entry file's media type. An image without a known suffix is generic."""
    if kind is ArtifactKind.IMAGE:
        return IMAGE_MIME_TYPES.get(entry.suffix.lower(), "application/octet-stream")
    return TEXT_MIME_TYPES[kind]


__all__ = ["IMAGE_MIME_TYPES", "SUFFIX_KINDS", "TEXT_MIME_TYPES", "ArtifactKind", "kind_of", "mime_of"]
