"""Shared utilities for the coding agent."""

from coding_agent.utils.ignore_file import DEFAULT_SKIP_DIRS, is_ignored
from coding_agent.utils.text import clip_text, compact_json, preview_text

__all__ = [
    "DEFAULT_SKIP_DIRS",
    "clip_text",
    "compact_json",
    "is_ignored",
    "preview_text",
]
