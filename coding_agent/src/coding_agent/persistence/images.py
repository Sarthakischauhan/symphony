"""Session-local content-addressed images; remote URLs are never fetched."""
from __future__ import annotations

import base64
import binascii
import hashlib
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from core_ai.content import normalize_content
from coding_agent.persistence.artifacts import publish, safe_path


_IMAGE_TYPES = {"image", "image_url", "input_image"}


def archive(value: Any, directory: Path) -> Any:
    """Copy embedded/local image parts to disk without mutating caller data."""
    if isinstance(value, list):
        return [archive(item, directory) for item in value]
    if not isinstance(value, dict):
        return value
    if value.get("type") in _IMAGE_TYPES or any(
        key in value for key in ("inlineData", "inline_data", "fileData", "file_data")
    ):
        if value.get("archive_path"):
            _image_path(value["archive_path"], directory)
            return dict(value)
        parts = normalize_content([value])
        if parts and parts[0].get("type") == "image":
            part = parts[0]
            data = part.get("data")
            payload = None
            try:
                if data:
                    payload = base64.b64decode("".join(str(data).split()), validate=True)
                else:
                    url = str(part.get("url") or value.get("path") or "")
                    parsed = urlparse(url)
                    if url and parsed.scheme in {"", "file"} and parsed.netloc in {"", "localhost"}:
                        payload = Path(unquote(parsed.path)).expanduser().read_bytes()
            except (OSError, ValueError, binascii.Error):
                # Preserve unsupported/missing inputs rather than discard content.
                return dict(value)
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
    """Return canonical provider-compatible image data plus an archived local URL."""
    if isinstance(value, list):
        return [hydrate(item, directory) for item in value]
    if not isinstance(value, dict):
        return value
    reference = value.get("archive_path")
    if reference is not None:
        path = _image_path(reference, directory)
        payload = path.read_bytes()
        return {
            "type": "image",
            "media_type": value.get("media_type", "image/png"),
            **({"filename": value["filename"]} if value.get("filename") else {}),
            "data": base64.b64encode(payload).decode("ascii"),
            "url": path.as_uri(),
        }
    return {key: hydrate(item, directory) for key, item in value.items()}


def _image_path(reference: Any, directory: Path) -> Path:
    reference = str(reference)
    digest = reference.removeprefix("images/")
    if reference != f"images/{digest}" or len(digest) != 64 or any(
        char not in "0123456789abcdef" for char in digest
    ):
        raise ValueError(f"invalid image archive reference: {reference!r}")
    return safe_path(directory, reference)
