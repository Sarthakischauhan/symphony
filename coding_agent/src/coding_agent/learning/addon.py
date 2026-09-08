"""Harness add-on that injects memory and reflects on a completed run."""

from __future__ import annotations

import re
from typing import Any, Callable, Optional

from core_ai.content import text_from_content
from core_ai.types import Message
from core_harness.addons import Addon

from coding_agent.learning.loop import LearningLoop
from coding_agent.learning.store import MEMORY_CONTEXT_PREFIX


_MEMORY_BLOCK = re.compile(
    r"\n*" + re.escape(MEMORY_CONTEXT_PREFIX) + r"(?:\n[^\n]+)*"
)


def strip_memory_context(content: str) -> str:
    """Remove previously injected labeled memory blocks from system text."""
    return _MEMORY_BLOCK.sub("", content).rstrip()


class LearningAddon(Addon):
    """Inject relevant memory each turn and schedule post-run reflection.

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
        self._last_context: str | None = None

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
        if context == self._last_context:
            return
        self._last_context = context
        for message in messages:
            if isinstance(message, Message) and message.role == "system":
                base = strip_memory_context(text_from_content(message.content))
                message.content = f"{base}\n\n{context}" if context else base
                break

    def fork_for_child(self, parent_harness: Any) -> None:
        del parent_harness
        return None

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
        )
