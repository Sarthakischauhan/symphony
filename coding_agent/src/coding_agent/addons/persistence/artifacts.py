"""Safe session artifact paths and atomic publication helpers."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def safe_path(root: Path, *parts: str) -> Path:
    """Reject symlinks, including links that happen to point inside the root."""
    path = root
    if root.is_symlink():
        raise ValueError(f"unsafe artifact directory: {root}")
    for part in parts:
        component = Path(part)
        if component.is_absolute() or any(p in {".", ".."} for p in component.parts):
            raise ValueError(f"unsafe artifact path: {part!r}")
        for name in component.parts:
            path = path / name
            if path.is_symlink():
                raise ValueError(f"unsafe artifact symlink: {path}")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"artifact path escapes root: {path}")
    return path


def fsync_dir(directory: Path) -> None:
    """Make a rename or create durable. The file fsync alone does not."""
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def publish(path: Path, payload: bytes) -> None:
    """Publish a complete file using a unique sibling temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError(f"unsafe artifact symlink: {path}")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    replaced = False
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        replaced = True
        fsync_dir(path.parent)
    finally:
        if not replaced:
            Path(temporary).unlink(missing_ok=True)


def append_bytes(path: Path, payload: bytes) -> None:
    """Append one durable record. The line is fsynced before this returns.

    The directory is fsynced only when this call created the file: appending
    to an existing file adds no directory entry, and the file fsync already
    makes the new length durable.
    """
    if not payload:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError(f"unsafe artifact symlink: {path}")
    created = not path.exists()
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o644)
    try:
        view = payload
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError(f"short write to {path}")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    if created:
        fsync_dir(path.parent)


def _snapshot_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


def snapshot(path: Path, payload: dict[str, Any]) -> None:
    publish(path, _snapshot_bytes(payload))


def refresh_snapshot(path: Path, payload: dict[str, Any]) -> None:
    """Publish ``payload`` only when the file is missing or holds other bytes.

    Re-reading a journal repairs artifacts a crash left stale. When they are
    already current this costs one small read instead of two fsyncs.
    """
    encoded = _snapshot_bytes(payload)
    if not path.is_symlink():
        try:
            if path.read_bytes() == encoded:
                return
        except OSError:
            pass
    publish(path, encoded)
