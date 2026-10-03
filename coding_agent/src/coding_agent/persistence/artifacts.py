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


def publish(path: Path, payload: bytes) -> None:
    """Publish a complete file using a unique sibling temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError(f"unsafe artifact symlink: {path}")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def snapshot(path: Path, payload: dict[str, Any]) -> None:
    publish(path, (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
