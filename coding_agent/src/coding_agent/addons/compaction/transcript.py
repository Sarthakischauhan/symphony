"""Render dropped turns for the model and build the compacted-context message."""

from __future__ import annotations

import json
from typing import List, Sequence

from core_ai.content import text_from_content
from core_ai.types import Message
from core_harness.addons.compaction import (
    COMPACTION_CONTINUATION,
    compaction_header,
    dropped_turn_facts,
)

DEFAULT_TRANSCRIPT_MAX_CHARS = 24_000
_MESSAGE_PREVIEW_CHARS = 700
_TOOL_RESULT_PREVIEW_CHARS = 400
_TOOL_ARGS_PREVIEW_CHARS = 160


def _clamp(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _tool_call_line(call: dict) -> str:
    function = call.get("function") or {}
    name = str(function.get("name") or "tool")
    raw_arguments = function.get("arguments") or ""
    if isinstance(raw_arguments, str):
        try:
            decoded = json.loads(raw_arguments) if raw_arguments else {}
        except json.JSONDecodeError:
            decoded = raw_arguments
    else:
        decoded = raw_arguments
    arguments = decoded if isinstance(decoded, str) else json.dumps(decoded, sort_keys=True)
    return f"assistant → {name}({_clamp(arguments, _TOOL_ARGS_PREVIEW_CHARS)})"


def render_dropped_turns(
    turns: Sequence[Sequence[Message]],
    *,
    max_chars: int = DEFAULT_TRANSCRIPT_MAX_CHARS,
) -> str:
    """Plain-text transcript of the turns about to be dropped.

    Each message is clamped individually; if the whole transcript is still too
    long the middle is elided so both the earliest asks and the most recent
    work reach the model.
    """
    names: dict[str, str] = {}
    lines: List[str] = []
    for turn in turns:
        for message in turn:
            if message.role == "assistant" and message.tool_calls:
                for call in message.tool_calls:
                    function = call.get("function") or {}
                    names[str(call.get("id") or "")] = str(function.get("name") or "tool")
                text = text_from_content(message.content).strip()
                if text:
                    lines.append(f"assistant: {_clamp(text, _MESSAGE_PREVIEW_CHARS)}")
                lines.extend(_tool_call_line(call) for call in message.tool_calls)
            elif message.role == "tool":
                name = names.get(str(message.tool_call_id or ""), "tool")
                body = text_from_content(message.content)
                lines.append(f"tool[{name}]: {_clamp(body, _TOOL_RESULT_PREVIEW_CHARS)}")
            else:
                text = text_from_content(message.content)
                lines.append(f"{message.role}: {_clamp(text, _MESSAGE_PREVIEW_CHARS)}")

    transcript = "\n".join(lines)
    if len(transcript) <= max_chars:
        return transcript
    head_budget = max_chars // 2
    tail_budget = max_chars - head_budget
    head: List[str] = []
    used = 0
    for line in lines:
        if used + len(line) + 1 > head_budget:
            break
        head.append(line)
        used += len(line) + 1
    tail: List[str] = []
    used = 0
    for line in reversed(lines[len(head):]):
        if used + len(line) + 1 > tail_budget:
            break
        tail.insert(0, line)
        used += len(line) + 1
    omitted = len(lines) - len(head) - len(tail)
    return "\n".join([*head, f"… ({omitted} lines omitted) …", *tail])


def build_compacted_message(
    turns: Sequence[Sequence[Message]],
    *,
    narrative: str,
    tokens: int,
) -> Message:
    """Compacted-context message: header, model narrative, deterministic facts."""
    dropped_messages = sum(len(turn) for turn in turns)
    lines = compaction_header(dropped_messages, tokens=tokens)
    lines.append("Summary of the dropped work:")
    lines.append(narrative.strip())
    lines.extend(dropped_turn_facts(turns))
    lines.append(COMPACTION_CONTINUATION)
    return Message(role="user", content="\n".join(lines))


__all__ = [
    "DEFAULT_TRANSCRIPT_MAX_CHARS",
    "build_compacted_message",
    "render_dropped_turns",
]
