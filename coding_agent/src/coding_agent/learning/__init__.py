"""Self-learning helpers: optional LLM reviewer, proposed vs trusted lessons."""

from coding_agent.learning.loop import LearningLoop
from coding_agent.learning.sanitize import redact_secrets, sanitize_task, sanitize_text
from coding_agent.learning.store import (
    LearningStore,
    Lesson,
    ProposedLesson,
    TrustedLesson,
)

__all__ = [
    "LearningLoop",
    "LearningStore",
    "Lesson",
    "ProposedLesson",
    "TrustedLesson",
    "redact_secrets",
    "sanitize_task",
    "sanitize_text",
]
