"""Heuristic token estimation and per-message size accounting."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from core_ai.content import estimate_content_tokens
from core_ai.types import Message


def estimate_text_tokens(text: str) -> int:
    """Rough char/4 token estimate used when provider usage is missing."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def estimate_message_tokens(message: Message) -> int:
    tokens = estimate_content_tokens(message.content)
    if message.tool_calls:
        try:
            tokens += estimate_text_tokens(json.dumps(message.tool_calls))
        except TypeError:
            tokens += estimate_text_tokens(str(message.tool_calls))
    if message.tool_call_id:
        tokens += estimate_text_tokens(message.tool_call_id)
    return max(tokens, 1)


def message_size_breakdown(messages: List[Message]) -> List[Dict[str, Any]]:
    """Return per-message token estimates for control-plane diagnostics."""
    sizes: List[Dict[str, Any]] = []
    for index, message in enumerate(messages):
        entry: Dict[str, Any] = {
            "index": index,
            "role": message.role,
            "tokens": estimate_message_tokens(message),
        }
        if message.tool_call_id:
            entry["tool_call_id"] = message.tool_call_id
        sizes.append(entry)
    return sizes


def estimate_prompt_tokens(messages: List[Message]) -> int:
    return sum(estimate_message_tokens(message) for message in messages)


def estimate_completion_tokens(
    assistant_text: str,
    *,
    tool_arguments_json: str = "",
) -> int:
    return estimate_text_tokens(assistant_text) + estimate_text_tokens(tool_arguments_json)
