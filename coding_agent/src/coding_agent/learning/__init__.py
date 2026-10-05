"""Durable capture, observation consolidation, and curated-topic recall."""

from __future__ import annotations

from typing import Any

from coding_agent._lazy import resolve
from coding_agent.learning.loop import LearningLoop, LearningReview, two_line_summary
from coding_agent.learning.sanitize import redact_secrets, sanitize_task, sanitize_text
from coding_agent.learning.store import MEMORY_CONTEXT_PREFIX, LearningStore, Lesson

_ADDON_EXPORTS = {
    "LearningAddon": ("coding_agent.addon.learning", "LearningAddon"),
    "strip_memory_context": ("coding_agent.addon.learning", "strip_memory_context"),
}

__all__ = [
    "MEMORY_CONTEXT_PREFIX",
    "LearningAddon",
    "LearningLoop",
    "LearningReview",
    "LearningStore",
    "Lesson",
    "strip_memory_context",
    "redact_secrets",
    "sanitize_task",
    "sanitize_text",
    "two_line_summary",
]


def __getattr__(name: str) -> Any:
    return resolve(globals(), name, _ADDON_EXPORTS)
