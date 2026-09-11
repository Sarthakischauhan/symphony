"""Harness add-on that injects memory and reflects on a completed run."""

from __future__ import annotations

import re
from typing import Any, Callable, Optional

from core_ai.content import text_from_content
from core_ai.types import Message
from core_harness.addons import Addon

from coding_agent.learning.loop import LearningLoop
from coding_agent.learning.store import MEMORY_CONTEXT_PREFIX


LEARNING_IDLE_DELAY_SECONDS = 120.0

_MEMORY_BLOCK = re.compile(
    r"\n*" + re.escape(MEMORY_CONTEXT_PREFIX) + r"(?:\n[^\n]+)*"
)


def strip_memory_context(content: str) -> str:
    """Remove previously injected labeled memory blocks from system text."""
    return _MEMORY_BLOCK.sub("", content).rstrip()


def apply_memory_context(content: str, context: str) -> str:
    """Write ``context`` in place of any prior labeled memory block."""
    base = strip_memory_context(content)
    return f"{base}\n\n{context}" if context else base


def _has_desired_memory(content: str, context: str) -> bool:
    """True when the system text already carries the exact queried block."""
    if context:
        return context in content
    return MEMORY_CONTEXT_PREFIX not in content


class LearningAddon(Addon):
    """Inject relevant memory each turn and schedule post-run reflection.

    Review waits ``LEARNING_IDLE_DELAY_SECONDS`` (two minutes) after a run
    finishes with no further run. A new user message cancels that review
    (pending delay or in-flight) so ``run_summary`` is not shown.

    Children do not inherit this add-on. Plan-mode runs can skip review via
    ``should_review`` while still receiving memory through ``before_turn``.
    """

    name = "learning"

    def __init__(
        self,
        loop: LearningLoop,
        *,
        should_review: Optional[Callable[[], bool]] = None,
        should_inject: Optional[Callable[[], bool]] = None,
    ) -> None:
        self.loop = loop
        self.should_review = should_review or (lambda: True)
        self.should_inject = should_inject or (lambda: True)

    async def before_turn(self, **payload: Any) -> None:
        """Replace the labeled memory block on the current turn's system message."""
        if not self.should_inject():
            return
        messages = payload.get("messages") or []
        task = next(
            (text_from_content(message.content) for message in reversed(messages)
             if isinstance(message, Message) and message.role == "user"),
            "",
        )
        context = self.loop.store.query(
            task,
            limit=self.loop.context_limit,
            max_chars=self.loop.context_max_chars,
        )
        for message in messages:
            if isinstance(message, Message) and message.role == "system":
                current = text_from_content(message.content)
                if _has_desired_memory(current, context):
                    return
                message.content = apply_memory_context(current, context)
                break

    def fork_for_child(self, parent_harness: Any) -> None:
        del parent_harness
        return None

    async def before_run(self, **payload: Any) -> None:
        del payload
        self.loop.cancel()

    async def after_run(self, **payload: Any) -> None:
        if not self.should_review():
            return
        result = payload.get("result")
        if result is None:
            return
        self.loop.schedule(
            str(payload.get("task") or ""),
            result,
            emit=payload.get("emit"),
            delay_seconds=LEARNING_IDLE_DELAY_SECONDS,
        )
