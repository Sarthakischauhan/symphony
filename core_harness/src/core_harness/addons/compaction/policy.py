"""Keep-system-recent compaction policy.

``plan_keep_drop`` is the shared keep/drop rule: system prompt, pinned first
user task, atomic assistant/tool groups, recent window, token target.
``KeepSystemRecentCompactor`` applies it and writes a template summary with no
provider call. Products that summarise with a model call the same planner and
supply their own summary message.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol, Sequence

from core_ai.content import text_from_content
from core_ai.types import Content, Message

from core_harness.context.compact import (
    COMPACTED_CONTEXT_MARK,
    estimate_prompt_tokens,
    normalize_tool_protocol,
    _tool_names,
    _tool_refs,
)


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


COMPACTION_CONTINUATION = (
    "Continue from the messages below. Do not re-fetch already observed "
    "paths unless they changed. Do not ask the user to repeat dropped work."
)


def compaction_header(dropped_messages: int, *, tokens: int) -> List[str]:
    """Opening lines shared by every compacted-context message."""
    return [
        COMPACTED_CONTEXT_MARK,
        f"Dropped {dropped_messages} earlier message(s) (~{tokens:,} tokens).",
    ]


def dropped_turn_facts(turns: Sequence[Sequence[Message]]) -> List[str]:
    """Deterministic facts about dropped turns: asks, tools used, paths seen."""
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

    lines: List[str] = []
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
    return lines


def summarize_dropped_turns(turns: Sequence[Sequence[Message]], *, tokens: int) -> Message:
    """Template summary of dropped turns; no model call."""
    dropped_messages = sum(len(turn) for turn in turns)
    lines = compaction_header(dropped_messages, tokens=tokens)
    lines.extend(dropped_turn_facts(turns))
    lines.append(COMPACTION_CONTINUATION)
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


def _tool_result_count(blocks: Sequence[Sequence[Message]]) -> int:
    return sum(message.role == "tool" for block in blocks for message in block)


def _split_recent_tool_blocks(
    remainder: List[List[Message]],
    *,
    keep_recent_tools: int,
) -> tuple[List[List[Message]], List[List[Message]]]:
    """Keep the suffix containing the latest tool results and their call groups.

    When a conversation has no tools, keep the latest ``keep_recent_tools``
    message blocks so text-only conversations can still be compacted.
    """
    total_tools = _tool_result_count(remainder)
    if total_tools == 0:
        split = max(len(remainder) - keep_recent_tools, 0)
        return remainder[:split], remainder[split:]

    wanted = min(keep_recent_tools, total_tools)
    selected: List[List[Message]] = []
    selected_tools = 0
    dropped_end = 0
    for index in range(len(remainder) - 1, -1, -1):
        block = remainder[index]
        selected.insert(0, block)
        selected_tools += _tool_result_count([block])
        dropped_end = index
        if selected_tools >= wanted:
            previous = index - 1
            if previous >= 0 and any(
                message.role == "user" for message in remainder[previous]
            ):
                selected.insert(0, remainder[previous])
                dropped_end = previous
            break
    else:
        dropped_end = 0
        selected = list(remainder)
    return remainder[:dropped_end], selected


def _flatten(blocks: Sequence[Sequence[Message]]) -> List[Message]:
    return [message for group in blocks for message in group]


def compaction_target(
    target_tokens: Optional[int],
    context_limit: Optional[int],
) -> Optional[int]:
    """Token budget a compact should land under; a third of the window by default."""
    if target_tokens is not None:
        return target_tokens
    if context_limit is not None:
        return max(context_limit // 3, 1)
    return None


@dataclass
class KeepDropPlan:
    """Outcome of ``plan_keep_drop``.

    ``leading`` is the system prompt plus the pinned original task; ``dropped``
    and ``kept`` are atomic assistant/tool groups in conversation order.
    """

    leading: List[Message] = field(default_factory=list)
    dropped: List[List[Message]] = field(default_factory=list)
    kept: List[List[Message]] = field(default_factory=list)

    @property
    def dropped_messages(self) -> List[Message]:
        return _flatten(self.dropped)

    @property
    def dropped_tokens(self) -> int:
        return estimate_prompt_tokens(self.dropped_messages)

    def assemble(self, summary: Optional[Message]) -> List[Message]:
        """``leading`` + ``summary`` (when there is dropped history) + ``kept``."""
        middle = [summary] if summary is not None and self.dropped else []
        return self.leading + middle + _flatten(self.kept)

    def template_summary(self) -> Optional[Message]:
        if not self.dropped:
            return None
        return summarize_dropped_turns(self.dropped, tokens=self.dropped_tokens)


def plan_keep_drop(
    messages: List[Message],
    *,
    keep_recent_tools: int,
    target_tokens: Optional[int] = None,
    context_limit: Optional[int] = None,
) -> KeepDropPlan:
    """Decide what to keep and what to drop; no summary is written here.

    Keeps the leading system prompt, the first real user message, and the suffix
    containing the latest ``keep_recent_tools`` tool results. Assistant/tool
    groups stay together so the provider protocol stays valid. The token target
    is best-effort: protected recent tool results are never stubbed or dropped.
    """
    if keep_recent_tools < 1:
        raise ValueError("keep_recent_tools must be >= 1")
    valid = normalize_tool_protocol(messages)
    system = valid[0] if valid and valid[0].role == "system" else None
    rest = valid[1:] if system is not None else valid
    plan = KeepDropPlan(leading=[system] if system is not None else [])
    if not rest:
        return plan

    first_user = _first_user_message(rest)
    remainder: List[List[Message]] = []
    for block in _atomic_blocks(rest):
        if first_user is not None and first_user in block:
            leftover = [message for message in block if message is not first_user]
            if leftover:
                remainder.append(leftover)
        else:
            remainder.append(block)
    if first_user is not None:
        plan.leading.append(first_user)

    plan.dropped, plan.kept = _split_recent_tool_blocks(
        remainder, keep_recent_tools=keep_recent_tools
    )
    target = compaction_target(target_tokens, context_limit)
    protected_tools = min(keep_recent_tools, _tool_result_count(remainder))
    while (
        target is not None
        and estimate_prompt_tokens(plan.assemble(plan.template_summary())) > target
        and len(plan.kept) > 1
    ):
        if protected_tools:
            break
        plan.dropped.append(plan.kept.pop(0))
    return plan


class KeepSystemRecentCompactor:
    """Keep the system prompt, the original task, and the most recent messages.

    Assistant/tool groups stay together so the provider protocol stays valid.
    Earlier tool groups are summarised while the latest tool results remain in
    full. Dropped messages become one deterministic template summary; this
    compactor never calls a provider.
    """

    def __init__(
        self,
        keep_recent_tools: int = 32,
        target_tokens: Optional[int] = None,
    ) -> None:
        if keep_recent_tools < 1:
            raise ValueError("keep_recent_tools must be >= 1")
        if target_tokens is not None and target_tokens < 1:
            raise ValueError("target_tokens must be positive or None")
        self.keep_recent_tools = keep_recent_tools
        self.target_tokens = target_tokens

    def plan(self, messages: List[Message], *, context_limit: Optional[int]) -> KeepDropPlan:
        return plan_keep_drop(
            messages,
            keep_recent_tools=self.keep_recent_tools,
            target_tokens=self.target_tokens,
            context_limit=context_limit,
        )

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
        plan = self.plan(messages, context_limit=context_limit)
        return plan.assemble(plan.template_summary())


__all__ = [
    "COMPACTION_CONTINUATION",
    "Compactor",
    "KeepDropPlan",
    "KeepSystemRecentCompactor",
    "compaction_header",
    "compaction_target",
    "dropped_turn_facts",
    "plan_keep_drop",
    "summarize_dropped_turns",
]
