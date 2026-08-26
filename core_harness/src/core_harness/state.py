"""Harness conversation state and pluggable compaction."""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol

from core_ai.types import Content, Message
from core_harness.config import DEFAULT_HARNESS_CONFIG
from core_harness.models import ToolCall
from core_harness.utils.tokens import estimate_prompt_tokens

# --- compaction.py ---
def normalize_tool_protocol(messages: List[Message]) -> List[Message]:
    """Drop incomplete assistant/tool groups which provider APIs reject."""
    normalized: List[Message] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        if message.role == "tool":
            index += 1
            continue
        if message.role != "assistant" or not message.tool_calls:
            normalized.append(message)
            index += 1
            continue

        expected = {
            str(call.get("id"))
            for call in message.tool_calls
            if call.get("id") is not None
        }
        group = [message]
        results: set[str] = set()
        cursor = index + 1
        while cursor < len(messages) and messages[cursor].role == "tool":
            tool_message = messages[cursor]
            if tool_message.tool_call_id in expected:
                group.append(tool_message)
                results.add(str(tool_message.tool_call_id))
            cursor += 1
        if expected and results == expected:
            normalized.extend(group)
        index = cursor
    return normalized


def _atomic_blocks(messages: List[Message]) -> List[List[Message]]:
    """Group an assistant tool declaration with all of its tool results."""
    blocks: List[List[Message]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        if message.role == "assistant" and message.tool_calls:
            block = [message]
            index += 1
            while index < len(messages) and messages[index].role == "tool":
                block.append(messages[index])
                index += 1
            blocks.append(block)
        else:
            blocks.append([message])
            index += 1
    return blocks


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
        valid = normalize_tool_protocol(messages)
        system = valid[0] if valid and valid[0].role == "system" else None
        rest = valid[1:] if system is not None else valid

        selected: List[List[Message]] = []
        selected_count = 0
        for block in reversed(_atomic_blocks(rest)):
            if selected and selected_count + len(block) > self.keep_recent:
                break
            selected.insert(0, block)
            selected_count += len(block)
            if selected_count >= self.keep_recent:
                break

        recent = [message for block in selected for message in block]
        return ([system] if system is not None else []) + recent

# --- state.py ---
DEFAULT_CONTEXT_LIMITS = DEFAULT_HARNESS_CONFIG.context_limits


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

__all__ = [
    "Compactor",
    "DEFAULT_CONTEXT_LIMITS",
    "HarnessState",
    "KeepSystemRecentCompactor",
    "normalize_tool_protocol",
]
