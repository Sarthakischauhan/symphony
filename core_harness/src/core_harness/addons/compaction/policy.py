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


__all__ = ["Compactor", "KeepSystemRecentCompactor"]
