"""Run-complete metrics, usage, and compaction notice phrasing."""

from __future__ import annotations

from typing import Any, Mapping


def count_label(count: int, noun: str) -> str:
    """``1 model call`` / ``44 model calls`` — shared by run metrics and wait copy."""
    suffix = "" if count == 1 else "s"
    return f"{count} {noun}{suffix}"


def compact_tokens(value: int) -> str:
    for divisor, suffix in ((1_000_000, "M"), (1_000, "k")):
        if value >= divisor:
            return f"{value / divisor:.2f}".rstrip("0").rstrip(".") + suffix
    return str(value)


def clock_duration(seconds: float) -> str:
    minutes, seconds = divmod(max(0, int(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def completed_run_text(
    *,
    elapsed_seconds: float | None,
    prompt_tokens: int,
    completion_tokens: int,
    estimated: bool,
    model_calls: int,
    tool_calls: int,
) -> str:
    elapsed = clock_duration(elapsed_seconds) if elapsed_seconds is not None else "—"
    estimate = "~" if estimated else ""
    return (
        f"{elapsed} (↑{estimate}{compact_tokens(prompt_tokens)} "
        f"↓{estimate}{compact_tokens(completion_tokens)})"
        f" · {count_label(model_calls, 'model call')}"
        f" · {count_label(tool_calls, 'tool call')}"
    )


def usage_thinking_text(
    *,
    prefix: str = "Thinking",
    turn: int | None,
    prompt_tokens: int,
    completion_tokens: int,
    reasoning_tokens: int,
    estimated: bool,
) -> str:
    if not (prompt_tokens or completion_tokens):
        turn_text = f" · turn {turn + 1}" if turn is not None else ""
        return f"{prefix}{turn_text}"
    estimate = "~" if estimated else ""
    text = (
        f"{prefix} · {estimate}{prompt_tokens:,} in / "
        f"{estimate}{completion_tokens:,} out"
    )
    if reasoning_tokens:
        text += f" · {reasoning_tokens:,} reasoning"
    return text


def compaction_notice(payload: Mapping[str, Any]) -> str:
    """Notice text with message counts and, when known, estimated token counts."""
    before = payload.get("message_count_before", "?")
    after = payload.get("message_count_after", "?")
    text = f"Compacted context · {before} → {after} messages"
    tokens_before = payload.get("estimated_tokens_before")
    tokens_after = payload.get("estimated_tokens_after")
    if isinstance(tokens_before, int) and isinstance(tokens_after, int):
        text += f" · ~{tokens_before:,} → ~{tokens_after:,} tokens"
    return text
