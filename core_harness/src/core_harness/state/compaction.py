"""Pluggable conversation compaction for context-window management."""

from __future__ import annotations

from typing import List, Optional, Protocol

from core_ai.types import Message


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
