"""Text formatting helpers shared by the coding agent UI."""

from __future__ import annotations

import json
from typing import Any, Mapping


def compact_json(value: Mapping[str, Any]) -> str:
    """Serialize a mapping compactly for single-line UI summaries."""
    if not value:
        return ""
    return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))


def clip_text(value: Any, limit: int = 420) -> str:
    """Trim text to a display limit while preserving a visual ellipsis."""
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}…"


def preview_text(value: Any, limit: int = 180) -> str:
    """Trim an event value for a short notice message."""
    text = str(value)
    return text if len(text) <= limit else f"{text[:limit]}…"
