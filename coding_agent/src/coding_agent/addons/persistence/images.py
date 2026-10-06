"""Session-local content-addressed images; remote URLs are never fetched."""
from __future__ import annotations

import base64
import binascii
import hashlib
from pathlib import Path
from typing import Any

from core_ai.content import IMAGE_MIME_BY_SUFFIX, normalize_content
from coding_agent.addons.persistence.artifacts import publish, safe_path


_IMAGE_TYPES = {"image", "image_url", "input_image"}
# Inline image parts only. A local path is read when the user attached it.
MAX_IMAGE_BYTES = 8 * 1024 * 1024


def archive(value: Any, directory: Path) -> Any:
    """Copy embedded image parts to disk without mutating caller data."""
    if isinstance(value, list):
        return [archive(item, directory) for item in value]
    if not isinstance(value, dict):
        return value
    if value.get("type") in _IMAGE_TYPES or any(
        key in value for key in ("inlineData", "inline_data", "fileData", "file_data")
    ):
        if value.get("archive_path"):
            try:
                _image_path(value["archive_path"], directory)
            except ValueError:
                return _unavailable(value, "invalid")
            return dict(value)
        parts = normalize_content([value])
        if parts and parts[0].get("type") == "image":
            part = parts[0]
            payload = _payload(value, part)
            if payload is not None:
                digest = hashlib.sha256(payload).hexdigest()
                relative = f"images/{digest}"
                path = _image_path(relative, directory)
                if not path.exists():
                    publish(path, payload)
                return {
                    "type": "image",
                    "media_type": part.get("media_type", "image/png"),
                    **({"filename": part["filename"]} if part.get("filename") else {}),
                    "archive_path": relative,
                }
    return {key: archive(item, directory) for key, item in value.items()}


def hydrate(value: Any, directory: Path) -> Any:
    """Restore image bytes. A bad or missing blob does not fail the caller."""
    if isinstance(value, list):
        return [hydrate(item, directory) for item in value]
    if not isinstance(value, dict):
        return value
    reference = value.get("archive_path")
    if reference is not None:
        try:
            path = _image_path(reference, directory)
            size = path.stat().st_size
            if size > MAX_IMAGE_BYTES:
                return _unavailable(value, "too_large")
            payload = path.read_bytes()
        except (OSError, ValueError):
            return _unavailable(value, "missing")
        digest = hashlib.sha256(payload).hexdigest()
        if f"images/{digest}" != str(reference):
            return _unavailable(value, "mismatch")
        return {
            "type": "image",
            "media_type": value.get("media_type", "image/png"),
            **({"filename": value["filename"]} if value.get("filename") else {}),
            "data": base64.b64encode(payload).decode("ascii"),
            "url": path.as_uri(),
        }
    return {key: hydrate(item, directory) for key, item in value.items()}


def _payload(value: dict[str, Any], part: dict[str, Any]) -> bytes | None:
    data = part.get("data")
    if data:
        try:
            payload = base64.b64decode("".join(str(data).split()), validate=True)
        except (ValueError, binascii.Error):
            return None
        if len(payload) > MAX_IMAGE_BYTES:
            return None
        return payload
    return _attached_file(value)


def _attached_file(value: dict[str, Any]) -> bytes | None:
    """Read only a path the user attached. Arbitrary file URLs stay untouched."""
    if value.get("user_attached") is not True:
        return None
    raw = value.get("attached_path")
    if not isinstance(raw, str) or not raw:
        return None
    path = Path(raw).expanduser()
    try:
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            return None
        if path.suffix.lower() not in IMAGE_MIME_BY_SUFFIX:
            return None
        if path.stat().st_size > MAX_IMAGE_BYTES:
            return None
        return path.read_bytes()
    except OSError:
        return None


def _unavailable(value: dict[str, Any], reason: str) -> dict[str, Any]:
    kept = {
        key: value[key]
        for key in ("type", "media_type", "filename", "archive_path")
        if key in value
    }
    kept.setdefault("type", "image")
    kept["unavailable"] = reason
    return kept


def _image_path(reference: Any, directory: Path) -> Path:
    reference = str(reference)
    digest = reference.removeprefix("images/")
    if reference != f"images/{digest}" or len(digest) != 64 or any(
        char not in "0123456789abcdef" for char in digest
    ):
        raise ValueError(f"invalid image archive reference: {reference!r}")
    return safe_path(directory, reference)
