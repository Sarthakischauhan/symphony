"""Harness conversation state and context-window reports."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, List, Optional, Sequence

from core_ai.content import text_from_content
from core_ai.types import Content, Message
from core_harness.config import default_context_limits
from core_harness.models import ToolCall
from core_harness.context.compact import (
    DEFAULT_PRUNE_KEEP_RECENT,
    estimate_message_tokens,
    estimate_prompt_tokens,
    messages_for_model,
    _is_cleared_tool_result,
    _tool_names,
)

if TYPE_CHECKING:
    from core_harness.addons.compaction import Compactor

# --- context report ---
@dataclass(frozen=True)
class ContextBucket:
    role: str
    label: str
    tokens: int
    count: int


@dataclass(frozen=True)
class ContextMessage:
    index: int
    role: str
    tokens: int
    sent_tokens: int
    stubbed: bool
    tool_name: Optional[str]
    preview: str


@dataclass(frozen=True)
class ContextReport:
    stored_tokens: int
    sent_tokens: int
    context_limit: Optional[int]
    message_count: int
    tool_result_count: int
    stubbed_result_count: int
    buckets: tuple[ContextBucket, ...]
    sent_buckets: tuple[ContextBucket, ...]
    messages: tuple[ContextMessage, ...]

    @property
    def utilization(self) -> Optional[float]:
        if not self.context_limit:
            return None
        return min(self.stored_tokens / self.context_limit, 1.0)

    @property
    def sent_utilization(self) -> Optional[float]:
        if not self.context_limit:
            return None
        return min(self.sent_tokens / self.context_limit, 1.0)


_ROLE_LABELS = {
    "system": "System",
    "user": "Messages",
    "assistant": "Assistant",
    "tool": "Tool results",
}


def _buckets_for(messages: Sequence[Message]) -> tuple[ContextBucket, ...]:
    tokens: Dict[str, int] = {role: 0 for role in _ROLE_LABELS}
    counts: Dict[str, int] = {role: 0 for role in _ROLE_LABELS}
    for message in messages:
        role = message.role if message.role in tokens else "user"
        tokens[role] += estimate_message_tokens(message)
        counts[role] += 1
    return tuple(
        ContextBucket(role=role, label=label, tokens=tokens[role], count=counts[role])
        for role, label in _ROLE_LABELS.items()
    )


def build_context_report(
    messages: List[Message],
    *,
    context_limit: Optional[int] = None,
    keep_recent_tool_results: int = DEFAULT_PRUNE_KEEP_RECENT,
    prune_tokens: Optional[int] = None,
) -> ContextReport:
    """Stored conversation vs the payload that would be sent to the model."""
    sent = messages_for_model(
        messages,
        keep_recent=keep_recent_tool_results,
        prune_tokens=prune_tokens,
    )
    names = _tool_names(messages)
    entries: List[ContextMessage] = []
    stubbed = 0
    tools = 0
    for index, (stored, outgoing) in enumerate(zip(messages, sent)):
        is_tool = stored.role == "tool"
        is_stubbed = is_tool and _is_cleared_tool_result(outgoing.content) and not _is_cleared_tool_result(
            stored.content
        )
        if is_tool:
            tools += 1
        if is_stubbed or (is_tool and _is_cleared_tool_result(stored.content)):
            stubbed += 1
        preview = " ".join(text_from_content(stored.content).split())
        if len(preview) > 72:
            preview = preview[:69] + "…"
        entries.append(
            ContextMessage(
                index=index,
                role=stored.role,
                tokens=estimate_message_tokens(stored),
                sent_tokens=estimate_message_tokens(outgoing),
                stubbed=is_stubbed or (is_tool and _is_cleared_tool_result(stored.content)),
                tool_name=names.get(str(stored.tool_call_id or "")) if is_tool else None,
                preview=preview,
            )
        )
    return ContextReport(
        stored_tokens=estimate_prompt_tokens(messages),
        sent_tokens=estimate_prompt_tokens(sent),
        context_limit=context_limit,
        message_count=len(messages),
        tool_result_count=tools,
        stubbed_result_count=stubbed,
        buckets=_buckets_for(messages),
        sent_buckets=_buckets_for(sent),
        messages=tuple(entries),
    )


# --- state.py ---
DEFAULT_CONTEXT_LIMITS = default_context_limits()


EmitEvent = Callable[[str, Dict[str, Any]], Awaitable[None]]


class HarnessState:
    """Owns harness message transitions and context-window management."""

    def __init__(
        self,
        *,
        context_limits: Optional[Dict[str, int]] = None,
        context_warn_threshold: Optional[int] = None,
        context_compact_threshold: Optional[int] = None,
        compactor: Optional[Compactor] = None,
        context_target_tokens: Optional[int] = None,
    ) -> None:
        self.context_limits = {
            **DEFAULT_CONTEXT_LIMITS,
            **(context_limits or {}),
        }
        self.context_warn_threshold = context_warn_threshold
        self.context_compact_threshold = context_compact_threshold
        self.compactor = compactor
        if context_target_tokens is not None and context_target_tokens < 1:
            raise ValueError("context_target_tokens must be positive or None")
        self.context_target_tokens = context_target_tokens

    def add_user_message(self, messages: List[Message], content: Content) -> None:
        messages.append(Message(role="user", content=content))

    def add_assistant_message(
        self,
        messages: List[Message],
        content: str,
        tool_calls: Optional[List[ToolCall]] = None,
    ) -> None:
        payload = None
        if tool_calls:
            payload = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments),
                    },
                }
                for call in tool_calls
            ]
        messages.append(Message(role="assistant", content=content, tool_calls=payload))

    def add_tool_message(
        self,
        messages: List[Message],
        tool_call: ToolCall,
        content: Content,
    ) -> None:
        messages.append(
            Message(role="tool", content=content, tool_call_id=tool_call.id)
        )

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

    def should_compact(
        self,
        context_left: Optional[int],
        estimated_tokens: Optional[int] = None,
    ) -> bool:
        return (
            self.compactor is not None
            and (
                (
                    self.context_target_tokens is not None
                    and estimated_tokens is not None
                    and estimated_tokens >= self.context_target_tokens
                )
                or (
                    self.context_compact_threshold is not None
                    and context_left is not None
                    and context_left <= self.context_compact_threshold
                )
            )
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
        if not self.should_compact(context_left, estimate_prompt_tokens(messages)):
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

