"""Compact a persisted conversation on demand (the TUI's ``/compact``).

Why: a manual compaction runs outside a harness turn, so it has to load the
saved conversation, compact it with the mounted compactor, tell the other
addons, and save the result itself.
"""

from __future__ import annotations

from typing import Any, Callable

from core_harness import CoreHarness, Persistence
from core_harness.context import estimate_prompt_tokens


async def compact_persisted_conversation(
    harness: CoreHarness,
    persistence: Persistence,
    *,
    session_id: str,
    emit: Callable[..., Any],
) -> tuple[int, int]:
    """Compact the persisted conversation through the harness-mounted compactor.

    Emits ``compaction_started`` / ``compaction_completed`` (``manual`` set)
    with message and estimated token counts, fires ``on_compact`` for the
    other add-ons, and persists the result. Returns
    ``(messages_before, messages_after)``.
    """
    state = harness.state
    if state.compactor is None:
        raise RuntimeError("No compactor is mounted on the harness.")
    messages = await persistence.load_conversation(session_id=session_id)
    before = len(messages)
    if not messages:
        return (0, 0)

    context_limit = state.context_limit(harness.model_id)
    tokens_used = estimate_prompt_tokens(messages)
    context_left = max(context_limit - tokens_used, 0) if context_limit is not None else None
    compacted = await state.compact(
        messages,
        turn=0,
        context_limit=context_limit,
        tokens_used=tokens_used,
        context_left=context_left,
        emit=emit,
        manual=True,
    )
    await harness.notify_addons(
        "on_compact",
        turn=0,
        messages=compacted,
        context_limit=context_limit,
        tokens_used=tokens_used,
        context_left=context_left,
    )
    await persistence.save_conversation(
        session_id=session_id,
        messages=compacted,
    )
    return (before, len(compacted))


__all__ = ["compact_persisted_conversation"]
