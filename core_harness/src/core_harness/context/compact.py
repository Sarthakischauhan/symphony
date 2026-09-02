"""Token estimates, tool-result pruning, and protocol normalization."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence

from core_ai.content import estimate_content_tokens, text_from_content
from core_ai.types import Content, Message

CLEARED_TOOL_RESULT_MARK = "[tool result cleared:"
COMPACTED_CONTEXT_MARK = "[compacted earlier context]"
DEFAULT_PRUNE_KEEP_RECENT = 8
_REF_KEYS = ("path", "file", "filename", "target", "query", "pattern", "command")
_MIN_BOUND_KEEP = 10


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


def bound_tool_result(
    text: str,
    *,
    max_chars: Optional[int],
) -> str:
    """Cap a tool result at insert time, keeping a 40/60 head/tail split.

    Truncation is the TPM lever: the bounded text is what gets persisted, so
    later turns never re-pay the original size. The full original is discarded.
    """
    if max_chars is None or len(text) <= max_chars:
        return text

    omitted = len(text) - max_chars

    def marker(short: bool) -> str:
        details = f"{omitted:,} chars omitted"
        if short:
            return f"\n...[tool result truncated; {details}]...\n"
        return (
            f"\n...[tool result truncated; {details}"
            f" — already observed; do not re-run]...\n"
        )

    stamp = marker(short=False)
    if len(stamp) + _MIN_BOUND_KEEP > max_chars:
        stamp = marker(short=True)
    if len(stamp) >= max_chars:
        return stamp[:max_chars]

    available = max_chars - len(stamp)
    head = (available * 2) // 5
    tail = available - head
    suffix = text[-tail:] if tail else ""
    return text[:head] + stamp + suffix


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


def _preview_value(value: str, *, limit: int = 80) -> str:
    text = " ".join(value.split())
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def _call_name(call: Dict[str, Any]) -> str:
    function = call.get("function") if isinstance(call.get("function"), dict) else {}
    name = function.get("name") if isinstance(function, dict) else None
    if not name:
        raw = call.get("name")
        name = raw if isinstance(raw, str) else None
    return str(name or "tool")


def _call_arguments(call: Dict[str, Any]) -> Dict[str, Any]:
    function = call.get("function") if isinstance(call.get("function"), dict) else {}
    raw = function.get("arguments") if isinstance(function, dict) else call.get("arguments")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _tool_ref(call: Dict[str, Any]) -> str:
    name = _call_name(call)
    arguments = _call_arguments(call)
    for key in _REF_KEYS:
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return f"{name} {key}={_preview_value(value)}"
    return name


def _tool_names(messages: Sequence[Message]) -> Dict[str, str]:
    names: Dict[str, str] = {}
    for message in messages:
        if message.role != "assistant" or not message.tool_calls:
            continue
        for call in message.tool_calls:
            call_id = call.get("id")
            if call_id is None:
                continue
            names[str(call_id)] = _call_name(call)
    return names


def _tool_refs(messages: Sequence[Message]) -> Dict[str, str]:
    refs: Dict[str, str] = {}
    for message in messages:
        if message.role != "assistant" or not message.tool_calls:
            continue
        for call in message.tool_calls:
            call_id = call.get("id")
            if call_id is None:
                continue
            refs[str(call_id)] = _tool_ref(call)
    return refs


def _is_cleared_tool_result(content: Content) -> bool:
    return text_from_content(content).startswith(CLEARED_TOOL_RESULT_MARK)


def _cleared_stub(ref: str, text: str) -> str:
    return (
        f"{CLEARED_TOOL_RESULT_MARK} {ref} · {len(text):,} chars"
        f" — already observed; do not re-fetch unless it changed]"
    )


def prune_stale_tool_results(
    messages: List[Message],
    *,
    keep_recent: int = DEFAULT_PRUNE_KEEP_RECENT,
) -> List[Message]:
    """Return messages with older tool results replaced by a one-line stub.

    The most recent ``keep_recent`` tool messages stay intact. Stubs name the
    tool and path so the model does not re-read work it has already seen.
    Persisted history is not mutated.
    """
    if keep_recent < 0:
        raise ValueError("keep_recent must be >= 0")
    tool_indices = [index for index, message in enumerate(messages) if message.role == "tool"]
    if len(tool_indices) <= keep_recent:
        return list(messages)

    stale = set(tool_indices if keep_recent == 0 else tool_indices[:-keep_recent])
    refs = _tool_refs(messages)
    pruned: List[Message] = []
    for index, message in enumerate(messages):
        if index not in stale or _is_cleared_tool_result(message.content):
            pruned.append(message)
            continue
        text = text_from_content(message.content)
        ref = refs.get(str(message.tool_call_id or ""), "tool")
        pruned.append(message.model_copy(update={"content": _cleared_stub(ref, text)}))
    return pruned


def messages_for_model(
    messages: List[Message],
    *,
    keep_recent: int = DEFAULT_PRUNE_KEEP_RECENT,
    prune_tokens: Optional[int] = None,
) -> List[Message]:
    """Conversation sent to the model: linear until a token budget is crossed.

    Insert-time bounding is what keeps TPM in check. Old tool bodies are only
    stubbed once the estimated prompt is at least ``prune_tokens``. ``None``
    means never prune on send.
    """
    if prune_tokens is None or estimate_prompt_tokens(messages) < prune_tokens:
        return list(messages)
    return prune_stale_tool_results(messages, keep_recent=keep_recent)

