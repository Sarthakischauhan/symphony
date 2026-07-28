"""Pluggable conversation compaction for context-window management."""

from __future__ import annotations

from typing import List, Optional, Protocol

from core_ai.types import Message


class Compactor(Protocol):
    async def compact(
        self,
        messages: List[Message],
        *,
        turn: int,
        context_limit: Optional[int],
        tokens_used: int,
        context_left: Optional[int],
    ) -> List[Message]:
        """Return a reduced message list that fits better in the context window."""


class KeepSystemRecentCompactor:
    """Keep the leading system message (if any) and the most recent messages."""

    def __init__(self, keep_recent: int = 4) -> None:
        if keep_recent < 1:
            raise ValueError("keep_recent must be >= 1")
        self.keep_recent = keep_recent

    async def compact(
        self,
        messages: List[Message],
        *,
        turn: int,
        context_limit: Optional[int],
        tokens_used: int,
        context_left: Optional[int],
    ) -> List[Message]:
        del turn, context_limit, tokens_used, context_left
        if len(messages) <= self.keep_recent + 1:
            return list(messages)

        if messages and messages[0].role == "system":
            system = messages[0]
            rest = messages[1:]
            return [system, *rest[-self.keep_recent :]]

        return list(messages[-self.keep_recent :])
