"""Keep-system-recent compaction policy."""

from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional, Protocol, Sequence

from core_ai.content import text_from_content
from core_ai.types import Content, Message

from core_harness.context.compact import (
    COMPACTED_CONTEXT_MARK,
    DEFAULT_PRUNE_KEEP_RECENT,
    estimate_prompt_tokens,
    normalize_tool_protocol,
    prune_stale_tool_results,
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


class TurnSummarizer(Protocol):
    """Turn dropped turns into one compacted-context user message."""

    async def summarize(
        self,
        turns: Sequence[Sequence[Message]],
        *,
        tokens: int,
    ) -> Message:
        """Return a single ``user`` message that starts with ``COMPACTED_CONTEXT_MARK``."""


class TemplateTurnSummarizer:
    """Default summarizer: deterministic template, no provider call."""

    async def summarize(
        self,
        turns: Sequence[Sequence[Message]],
        *,
        tokens: int,
    ) -> Message:
        return summarize_dropped_turns(turns, tokens=tokens)


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


def _split_recent_blocks(
    remainder: List[List[Message]],
    *,
    keep_recent: int,
) -> tuple[List[List[Message]], List[List[Message]]]:
    """Split atomic blocks into ``(dropped, kept)`` keeping ~``keep_recent`` messages."""
    selected: List[List[Message]] = []
    selected_count = 0
    dropped_end = 0
    for index in range(len(remainder) - 1, -1, -1):
        block = remainder[index]
        if selected and selected_count + len(block) > keep_recent:
            dropped_end = index + 1
            break
        selected.insert(0, block)
        selected_count += len(block)
        dropped_end = index
        if selected_count >= keep_recent:
            break
    else:
        dropped_end = 0
        selected = list(remainder)
    return remainder[:dropped_end], selected


def _flatten(blocks: Sequence[Sequence[Message]]) -> List[Message]:
    return [message for group in blocks for message in group]


class KeepSystemRecentCompactor:
    """Keep the system prompt, the original task, and the most recent messages.

    ``keep_recent`` counts messages. Assistant/tool groups stay together so the
    provider protocol stays valid. A one-user N-tool loop is not one
    un-droppable unit: earlier tool groups can be summarised while the last
    ``keep_recent`` messages stay. Dropped messages become one summary message
    produced by ``summarizer`` (template by default; products can plug in a
    model-backed summarizer). Old tool bodies inside kept messages are stubbed
    only as a last resort if the compact is still over ``target_tokens``.
    """

    def __init__(
        self,
        keep_recent: int = 10,
        target_tokens: Optional[int] = None,
        keep_recent_tool_results: int = DEFAULT_PRUNE_KEEP_RECENT,
        *,
        summarizer: Optional[TurnSummarizer] = None,
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
        self.summarizer: TurnSummarizer = summarizer or TemplateTurnSummarizer()

    def plan(
        self,
        messages: List[Message],
        *,
        context_limit: Optional[int],
    ) -> tuple[List[Message], List[List[Message]], List[List[Message]]]:
        """Decide what to keep and what to drop without calling the summarizer.

        Returns ``(leading, dropped, kept)`` where ``leading`` is the system
        prompt plus pinned original task. The token target is enforced with the
        template summary as a size proxy so the summarizer runs exactly once.
        """
        valid = normalize_tool_protocol(messages)
        system = valid[0] if valid and valid[0].role == "system" else None
        rest = valid[1:] if system is not None else valid
        leading = [system] if system is not None else []
        if not rest:
            return leading, [], []

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
            leading.append(first_user)

        dropped, kept = _split_recent_blocks(remainder, keep_recent=self.keep_recent)
        target = self._target(context_limit)
        while (
            target is not None
            and estimate_prompt_tokens(self._proxy_assembly(leading, dropped, kept)) > target
            and len(kept) > 1
        ):
            dropped.append(kept.pop(0))
        return leading, dropped, kept

    def _target(self, context_limit: Optional[int]) -> Optional[int]:
        if self.target_tokens is not None:
            return self.target_tokens
        if context_limit is not None:
            return max(context_limit // 3, 1)
        return None

    @staticmethod
    def _proxy_assembly(
        leading: List[Message],
        dropped: List[List[Message]],
        kept: List[List[Message]],
    ) -> List[Message]:
        summary: List[Message] = []
        if dropped:
            summary = [
                summarize_dropped_turns(
                    dropped, tokens=estimate_prompt_tokens(_flatten(dropped))
                )
            ]
        return leading + summary + _flatten(kept)

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
        leading, dropped, kept = self.plan(messages, context_limit=context_limit)
        if not dropped and not kept:
            return leading

        summary: List[Message] = []
        if dropped:
            summary = [
                await self.summarizer.summarize(
                    dropped, tokens=estimate_prompt_tokens(_flatten(dropped))
                )
            ]
        compacted = leading + summary + _flatten(kept)
        target = self._target(context_limit)
        if target is not None and estimate_prompt_tokens(compacted) > target:
            compacted = prune_stale_tool_results(
                compacted, keep_recent=self.keep_recent_tool_results
            )
        return compacted


__all__ = [
    "COMPACTION_CONTINUATION",
    "Compactor",
    "KeepSystemRecentCompactor",
    "TemplateTurnSummarizer",
    "TurnSummarizer",
    "compaction_header",
    "dropped_turn_facts",
    "summarize_dropped_turns",
]
