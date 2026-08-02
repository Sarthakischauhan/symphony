
"""Mutable harness state and context-window management."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List, Optional

from core_ai.types import Message

from core_harness.state.compaction import Compactor
from core_harness.tokens import estimate_prompt_tokens


DEFAULT_CONTEXT_LIMITS = {
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4.1": 1047576,
    "gpt-4.1-mini": 1047576,
    "gpt-4.1-nano": 1047576,
}


EmitEvent = Callable[[str, Dict[str, Any]], Awaitable[None]]


class HarnessState:
    """State used by a harness while managing its context window."""

    def __init__(
        self,
        *,
        context_limits: Optional[Dict[str, int]] = None,
        context_warn_threshold: Optional[int] = None,
        context_compact_threshold: Optional[int] = None,
        compactor: Optional[Compactor] = None,
    ) -> None:
        self.context_limits = {
            **DEFAULT_CONTEXT_LIMITS,
            **(context_limits or {}),
        }
        self.context_warn_threshold = context_warn_threshold
        self.context_compact_threshold = context_compact_threshold
        self.compactor = compactor

    def context_limit(self, model_id: str) -> Optional[int]:
        if model_id in self.context_limits:
            return self.context_limits[model_id]

        model_name = model_id.split(":", 1)[-1]
        if model_name in self.context_limits:
            return self.context_limits[model_name]

        for known_model, limit in sorted(
            self.context_limits.items(), key=lambda item: len(item[0]), reverse=True
        ):
            if model_name.startswith(f"{known_model}-"):
                return limit

        return None

    def should_warn(self, context_left: Optional[int]) -> bool:
        return (
            self.context_warn_threshold is not None
            and context_left is not None
            and context_left <= self.context_warn_threshold
        )

    def should_compact(self, context_left: Optional[int]) -> bool:
        return (
            self.compactor is not None
            and self.context_compact_threshold is not None
            and context_left is not None
            and context_left <= self.context_compact_threshold
        )

    async def maybe_compact(
        self,
        messages: List[Message],
        *,
        turn: int,
        context_limit: Optional[int],
        tokens_used: int,
        context_left: Optional[int],
        emit: EmitEvent,
    ) -> List[Message]:
        """Compact messages when the configured context threshold is reached."""
        if not self.should_compact(context_left):
            return messages

        assert self.compactor is not None
        before_count = len(messages)
        before_tokens = estimate_prompt_tokens(messages)
        await emit(
            "compaction_started",
            {
                "turn": turn,
                "message_count": before_count,
                "tokens_used": tokens_used,
                "context_left": context_left,
                "threshold": self.context_compact_threshold,
            },
        )
        compacted = await self.compactor.compact(
            messages,
            turn=turn,
            context_limit=context_limit,
            tokens_used=tokens_used,
            context_left=context_left,
        )
        after_tokens = estimate_prompt_tokens(compacted)
        await emit(
            "compaction_completed",
            {
                "turn": turn,
                "message_count_before": before_count,
                "message_count_after": len(compacted),
                "estimated_tokens_before": before_tokens,
                "estimated_tokens_after": after_tokens,
            },
        )
        return compacted
