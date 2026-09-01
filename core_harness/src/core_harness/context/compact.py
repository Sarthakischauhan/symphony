"""Context compaction, pruning, and token estimates."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any, Dict, List, Optional, Protocol, Sequence

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


def _first_user_message(messages: Sequence[Message]) -> Optional[Message]:
    for message in messages:
        if message.role != "user":
            continue
        if text_from_content(message.content).startswith(COMPACTED_CONTEXT_MARK):
            continue
        return message
    return None


def _preview_ask(content: Content) -> str:
    text = " ".join(text_from_content(content).split())
    if len(text) > 120:
        return text[:117] + "…"
    return text


def _summarize_turns(turns: Sequence[Sequence[Message]], *, tokens: int) -> Message:
    asks: List[str] = []
    tools: Counter[str] = Counter()
    observed: List[str] = []
    names: Dict[str, str] = {}
    refs: Dict[str, str] = {}
    for turn in turns:
        names.update(_tool_names(turn))
        refs.update(_tool_refs(turn))
        for message in turn:
            if message.role == "user":
                preview = _preview_ask(message.content)
                if preview and not preview.startswith(COMPACTED_CONTEXT_MARK):
                    asks.append(preview)
            elif message.role == "tool":
                name = names.get(str(message.tool_call_id or ""), "tool")
                tools[name] += 1
                ref = refs.get(str(message.tool_call_id or ""), "")
                if ref and ref not in observed:
                    observed.append(ref)

    dropped_messages = sum(len(turn) for turn in turns)
    lines = [
        COMPACTED_CONTEXT_MARK,
        f"Dropped {dropped_messages} earlier message(s) (~{tokens:,} tokens).",
    ]
    if asks:
        shown = asks[:6]
        preview = "; ".join(f'"{ask}"' for ask in shown)
        if len(asks) > 6:
            preview += f"; … ({len(asks) - 6} more)"
        lines.append(f"User asks: {preview}")
    if tools:
        used = ", ".join(
            f"{name}×{count}" if count > 1 else name
            for name, count in tools.items()
        )
        lines.append(f"Tools used: {used}")
    if observed:
        shown_obs = observed[:10]
        extra = f"; … ({len(observed) - 10} more)" if len(observed) > 10 else ""
        lines.append("Already observed: " + "; ".join(shown_obs) + extra)
    lines.append(
        "Continue from the messages below. Do not re-fetch already observed "
        "paths unless they changed. Do not ask the user to repeat dropped work."
    )
    return Message(role="user", content="\n".join(lines))


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
    """Keep the system prompt, the original task, and the most recent messages.

    ``keep_recent`` counts messages. Assistant/tool groups stay together so the
    provider protocol stays valid. A one-user N-tool loop is not one
    un-droppable unit: earlier tool groups can be summarised while the last
    ``keep_recent`` messages stay. Dropped messages become a path-aware
    summary. Old tool bodies inside kept messages are stubbed only as a last
    resort if the compact is still over ``target_tokens``.
    """

    def __init__(
        self,
        keep_recent: int = 10,
        target_tokens: Optional[int] = None,
        keep_recent_tool_results: int = DEFAULT_PRUNE_KEEP_RECENT,
    ) -> None:
        if keep_recent < 1:
            raise ValueError("keep_recent must be >= 1")
        if target_tokens is not None and target_tokens < 1:
            raise ValueError("target_tokens must be positive or None")
        if keep_recent_tool_results < 0:
            raise ValueError("keep_recent_tool_results must be >= 0")
        self.keep_recent = keep_recent
        self.target_tokens = target_tokens
        self.keep_recent_tool_results = keep_recent_tool_results

    async def compact(
        self,
        messages: List[Message],
        *,
        turn: int,
        context_limit: Optional[int],
        tokens_used: int,
        context_left: Optional[int],
    ) -> List[Message]:
        del turn, tokens_used, context_left
        valid = normalize_tool_protocol(messages)
        system = valid[0] if valid and valid[0].role == "system" else None
        rest = valid[1:] if system is not None else valid
        if not rest:
            return valid

        first_user = _first_user_message(rest)
        remainder: List[List[Message]] = []
        for block in _atomic_blocks(rest):
            if first_user is not None and first_user in block:
                leftover = [message for message in block if message is not first_user]
                if leftover:
                    remainder.append(leftover)
            else:
                remainder.append(block)

        selected: List[List[Message]] = []
        selected_count = 0
        dropped_end = 0
        for index in range(len(remainder) - 1, -1, -1):
            block = remainder[index]
            if selected and selected_count + len(block) > self.keep_recent:
                dropped_end = index + 1
                break
            selected.insert(0, block)
            selected_count += len(block)
            dropped_end = index
            if selected_count >= self.keep_recent:
                break
        else:
            dropped_end = 0
            selected = list(remainder)

        dropped = remainder[:dropped_end]
        kept = selected
        pinned = [first_user] if first_user is not None else []

        def assemble(pending: List[List[Message]], kept_blocks: List[List[Message]]) -> List[Message]:
            summary: List[Message] = []
            if pending:
                pending_messages = [message for group in pending for message in group]
                summary = [_summarize_turns(pending, tokens=estimate_prompt_tokens(pending_messages))]
            leading = [system] if system is not None else []
            recent = [message for group in kept_blocks for message in group]
            return leading + pinned + summary + recent

        compacted = assemble(dropped, kept)
        target = self.target_tokens
        if target is None and context_limit is not None:
            target = max(context_limit // 3, 1)
        while (
            target is not None
            and estimate_prompt_tokens(compacted) > target
            and len(kept) > 1
        ):
            dropped.append(kept.pop(0))
            compacted = assemble(dropped, kept)
        if (
            target is not None
            and estimate_prompt_tokens(compacted) > target
        ):
            compacted = prune_stale_tool_results(
                compacted, keep_recent=self.keep_recent_tool_results
            )
        return compacted

