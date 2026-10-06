"""Harness add-on that adds memory to each request and reflects on a completed run."""

from __future__ import annotations

import logging
import re
import sqlite3
from typing import Any, Callable, Optional

from core_ai.content import text_from_content
from core_ai.types import Message
from core_harness.addons import Addon

from coding_agent.addons.learning.sanitize import sanitize_memory
from coding_agent.addons.learning.loop import LearningLoop
from coding_agent.addons.learning.store import MEMORY_CONTEXT_PREFIX, LearningStore


logger = logging.getLogger(__name__)

LEARNING_IDLE_DELAY_SECONDS = 0.0

_MEMORY_BLOCK = re.compile(
    r"\n*" + re.escape(MEMORY_CONTEXT_PREFIX) + r"(?:\n[^\n]+)*"
)


def strip_memory_context(content: str) -> str:
    """Remove labeled memory blocks from text (older builds wrote them into system)."""
    return _MEMORY_BLOCK.sub("", content).rstrip()


MEMORY_CONTEXT_KEY = "memory"


def inject_memory(
    store: LearningStore,
    messages: list[Any],
    *,
    limit: int,
    max_chars: int,
    context: Optional[dict[str, str]] = None,
) -> str:
    """Retrieve bounded reference data for the next model call.

    The block goes into the per-turn ``context`` the harness sends as a user
    message next to the latest task. It never edits the system message, so
    the system prefix stays byte-identical across turns. Returns the block.
    """
    # User-authored context only: assistant guesses and tool output are not
    # allowed to steer durable-memory retrieval. Exclude synthetic compactions.
    from core_harness.context import COMPACTED_CONTEXT_MARK

    users = [text_from_content(message.content) for message in messages
             if isinstance(message, Message) and message.role == "user"
             and not text_from_content(message.content).startswith(COMPACTED_CONTEXT_MARK)]
    task = users[-1] if users else ""
    recent = "\n".join(sanitize_memory(text, max_chars=400) for text in users[-4:-1])[:1200]
    try:
        memory = store.query(task, limit=limit, max_chars=max_chars,
                             recent_context=recent, include_preferences=True)
    except (OSError, UnicodeError, ValueError, sqlite3.Error):
        logger.warning("Memory retrieval unavailable; continuing without memory", exc_info=True)
        memory = ""
    if context is not None:
        if memory:
            context[MEMORY_CONTEXT_KEY] = memory
        else:
            context.pop(MEMORY_CONTEXT_KEY, None)
    try:
        store.archive_context("injected", task, memory)
    except (OSError, UnicodeError, ValueError, sqlite3.Error):
        logger.warning("Memory context archival unavailable", exc_info=True)
    return memory


def capture_memory(loop: LearningLoop, task: str, messages: list[Any]) -> None:
    """Memory I/O must never turn a successful agent turn into a failure."""
    try:
        loop.capture(task, messages)
    except (OSError, UnicodeError, ValueError, sqlite3.Error):
        logger.warning("Memory capture unavailable; agent turn continues", exc_info=True)


class LearningAddon(Addon):
    """Retrieve curated topics before inference and durably capture each turn.

    Capture input is persisted before background extraction. New user messages
    never discard pending jobs. Children bind their own capture loop.
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
        """Put memory in this turn's request context; the system message is left alone."""
        if not self.should_inject():
            return
        inject_memory(self.loop.store, payload.get("messages") or [],
                      limit=self.loop.context_limit, max_chars=self.loop.context_max_chars,
                      context=payload.get("context"))

    def fork_for_child(self, parent_harness: Any) -> None:
        """Skip inherit: child runs do not observe or record learning."""
        del parent_harness
        return None

    async def before_run(self, **payload: Any) -> None:
        self.task = next((text_from_content(m.content) for m in reversed(payload.get("messages") or [])
                          if isinstance(m, Message) and m.role == "user"), str(payload.get("task") or ""))
        self.loop.resume()

    async def after_turn(self, **payload: Any) -> None:
        if self.should_review():
            capture_memory(self.loop, getattr(self, "task", ""), payload.get("messages") or [])

    async def after_run(self, **payload: Any) -> None:
        if self.should_review() and payload.get("result") is not None:
            capture_memory(self.loop, getattr(self, "task", ""), payload["result"].messages)

    async def on_compact(self, **payload: Any) -> None:
        if self.should_review() and payload.get("messages"):
            capture_memory(self.loop, getattr(self, "task", ""), payload["messages"])


class SessionMemoryAddon(Addon):
    """Bind child-local memory tools without inheriting parent reflection tasks."""

    name = "session_memory"

    def __init__(
        self, store_factory: Callable[[str], LearningStore], *,
        context_limit: int = 6, context_max_chars: int = 1400,
        should_inject: bool = True,
    ) -> None:
        self.store_factory = store_factory
        self.context_limit = context_limit
        self.context_max_chars = context_max_chars
        self.should_inject = should_inject

    def attach(self, harness: Any) -> None:
        from coding_agent.tools.memory import MemoryGetTool, MemorySearchTool, MemoryTool

        self.store = self.store_factory(harness.session_id)
        self.loop = LearningLoop(self.store, registry=harness.registry, model_id=harness.model_id)
        # The harness normally shares tool objects with its parent. Replace only
        # memory so concurrent children cannot rebind the parent's store.
        for name, tool in list(harness.tools.items()):
            if isinstance(tool, (MemoryTool, MemorySearchTool, MemoryGetTool)):
                harness.tools[name] = type(tool)(tool.workspace, store=self.store)

    async def before_turn(self, **payload: Any) -> None:
        if not self.should_inject:
            return
        inject_memory(self.store, payload.get("messages") or [],
                      limit=self.context_limit, max_chars=self.context_max_chars,
                      context=payload.get("context"))

    async def before_run(self, **payload: Any) -> None:
        self.task = next((text_from_content(m.content) for m in reversed(payload.get("messages") or [])
                          if isinstance(m, Message) and m.role == "user"), str(payload.get("task") or ""))
        if self.should_inject:
            self.loop.resume()

    async def after_turn(self, **payload: Any) -> None:
        if self.should_inject:
            capture_memory(self.loop, getattr(self, "task", ""), payload.get("messages") or [])
