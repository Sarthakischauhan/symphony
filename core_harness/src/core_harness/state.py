"""Harness conversation state and pluggable compaction."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol, Sequence

from core_ai.content import text_from_content
from core_ai.types import Content, Message
from core_harness.config import DEFAULT_HARNESS_CONFIG
from core_harness.models import ToolCall
from core_harness.utils.tokens import estimate_message_tokens, estimate_prompt_tokens

CLEARED_TOOL_RESULT_MARK = "[tool result cleared:"
COMPACTED_CONTEXT_MARK = "[compacted earlier context]"
DEFAULT_PRUNE_KEEP_RECENT = 2

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


def _tool_names(messages: Sequence[Message]) -> Dict[str, str]:
    names: Dict[str, str] = {}
    for message in messages:
        if message.role != "assistant" or not message.tool_calls:
            continue
        for call in message.tool_calls:
            call_id = call.get("id")
            if call_id is None:
                continue
            function = call.get("function") if isinstance(call.get("function"), dict) else {}
            name = function.get("name") if isinstance(function, dict) else None
            if not name:
                raw = call.get("name")
                name = raw if isinstance(raw, str) else None
            names[str(call_id)] = str(name or "tool")
    return names


def _is_cleared_tool_result(content: Content) -> bool:
    return text_from_content(content).startswith(CLEARED_TOOL_RESULT_MARK)


def prune_stale_tool_results(
    messages: List[Message],
    *,
    keep_recent: int = DEFAULT_PRUNE_KEEP_RECENT,
) -> List[Message]:
    """Return messages with older tool results replaced by a one-line stub.

    The most recent ``keep_recent`` tool messages stay intact so the model can
    still see what it just did. Older results are not sent again — that is what
    made TPM climb past 200k after a couple dozen tool calls.
    """
    if keep_recent < 0:
        raise ValueError("keep_recent must be >= 0")
    tool_indices = [index for index, message in enumerate(messages) if message.role == "tool"]
    if len(tool_indices) <= keep_recent:
        return list(messages)

    stale = set(tool_indices if keep_recent == 0 else tool_indices[:-keep_recent])
    names = _tool_names(messages)
    pruned: List[Message] = []
    for index, message in enumerate(messages):
        if index not in stale or _is_cleared_tool_result(message.content):
            pruned.append(message)
            continue
        text = text_from_content(message.content)
        name = names.get(str(message.tool_call_id or ""), "tool")
        stub = f"{CLEARED_TOOL_RESULT_MARK} {name} · {len(text):,} chars]"
        pruned.append(message.model_copy(update={"content": stub}))
    return pruned


def _conversation_turns(messages: List[Message]) -> List[List[Message]]:
    """Group rest-of-conversation into user turns plus following assistant/tools."""
    turns: List[List[Message]] = []
    current: List[Message] = []
    for block in _atomic_blocks(messages):
        if block[0].role == "user":
            if current:
                turns.append(current)
            current = list(block)
            continue
        if not current:
            current = list(block)
        else:
            current.extend(block)
    if current:
        turns.append(current)
    return turns


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
    names: Dict[str, str] = {}
    for turn in turns:
        names.update(_tool_names(turn))
        for message in turn:
            if message.role == "user":
                preview = _preview_ask(message.content)
                if preview and not preview.startswith(COMPACTED_CONTEXT_MARK):
                    asks.append(preview)
            elif message.role == "tool":
                tools[names.get(str(message.tool_call_id or ""), "tool")] += 1

    lines = [
        COMPACTED_CONTEXT_MARK,
        f"Dropped {len(turns)} earlier turn(s) (~{tokens:,} tokens).",
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
    lines.append("Continue from the messages below. Do not ask the user to repeat dropped work.")
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
    """Keep the system prompt, the original task, and the most recent turns.

    ``keep_recent`` counts conversation turns (a user message plus the
    assistant/tool group that followed it), not raw messages. Old tool results
    inside kept turns are stubbed so compaction actually shrinks tokens instead
    of dropping the user's task at a random cutoff.
    """

    def __init__(
        self,
        keep_recent: int = 4,
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

        rest = prune_stale_tool_results(rest, keep_recent=self.keep_recent_tool_results)
        turns = _conversation_turns(rest)
        first_user = _first_user_message(rest)
        remainder: List[List[Message]] = []
        for turn in turns:
            if first_user is not None and first_user in turn:
                leftover = [message for message in turn if message is not first_user]
                if leftover:
                    remainder.append(leftover)
            else:
                remainder.append(turn)

        kept_turns = remainder[-self.keep_recent :]
        dropped = remainder[: -self.keep_recent] if len(remainder) > self.keep_recent else []
        pinned = [first_user] if first_user is not None else []

        def assemble(pending: List[List[Message]], kept: List[List[Message]]) -> List[Message]:
            summary: List[Message] = []
            if pending:
                pending_messages = [message for group in pending for message in group]
                summary = [_summarize_turns(pending, tokens=estimate_prompt_tokens(pending_messages))]
            leading = [system] if system is not None else []
            recent = [message for group in kept for message in group]
            return leading + pinned + summary + recent

        compacted = assemble(dropped, kept_turns)
        target = self.target_tokens
        if target is None and context_limit is not None:
            target = max(context_limit // 3, 1)
        while (
            target is not None
            and estimate_prompt_tokens(compacted) > target
            and len(kept_turns) > 1
        ):
            dropped.append(kept_turns.pop(0))
            compacted = assemble(dropped, kept_turns)
        return compacted


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
) -> ContextReport:
    """Stored conversation vs the payload that would be sent to the model."""
    sent = prune_stale_tool_results(messages, keep_recent=keep_recent_tool_results)
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
    "CLEARED_TOOL_RESULT_MARK",
    "COMPACTED_CONTEXT_MARK",
    "Compactor",
    "ContextBucket",
    "ContextMessage",
    "ContextReport",
    "DEFAULT_CONTEXT_LIMITS",
    "DEFAULT_PRUNE_KEEP_RECENT",
    "HarnessState",
    "KeepSystemRecentCompactor",
    "build_context_report",
    "normalize_tool_protocol",
    "prune_stale_tool_results",
]
