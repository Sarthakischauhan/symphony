"""Provider stream consumption for one model turn."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional, Protocol

from core_ai.registry import ModelRegistry
from core_ai.types import Message, StreamEvent

from core_harness.context import (
    estimate_completion_tokens,
    estimate_prompt_tokens,
    messages_for_model,
)
from core_harness.errors import HarnessCancelled, HarnessLimitExceeded
from core_harness.models import PendingToolCall, UsageTotals


class TurnStreamHost(Protocol):
    """Surface streaming needs from the active turn."""

    registry: ModelRegistry
    model_id: str
    reasoning_effort: Optional[str]
    tool_schemas: List[Dict[str, Any]]
    control_plane: Any
    tool_result_keep_recent: int
    tool_result_prune_tokens: Optional[int]

    def _cancelled(self) -> bool: ...

    def _cancel_reason(self) -> str: ...

    def _raise_if_cancelled(self) -> None: ...

    def _raise_if_runtime_exceeded(self) -> None: ...

    def _remaining_runtime(self) -> Optional[float]: ...

    def _runtime_exceeded_error(self) -> HarnessLimitExceeded: ...


@dataclass
class StreamedTurn:
    """Mutable stream state for one model attempt."""

    assistant_text: str = ""
    reasoning_texts: Dict[int, str] = field(default_factory=dict)
    pending_calls: Dict[int, PendingToolCall] = field(default_factory=dict)
    saw_usage: bool = False
    attempt_usage: UsageTotals = field(default_factory=UsageTotals)
    budget_tokens: int = 0
    estimated_message_tokens: int = 0


async def stream_model_turn(
    runner: TurnStreamHost,
    messages: List[Message],
    *,
    turn: int,
    usage: UsageTotals,
    estimated_message_tokens: int,
) -> StreamedTurn:
    """Consume the provider stream; mutate ``usage``. Return text, calls, budget."""
    streamed = StreamedTurn(estimated_message_tokens=estimated_message_tokens)
    streamed.budget_tokens = estimated_message_tokens
    async for event in iter_provider_events(runner, messages):
        await dispatch_stream_event(
            event,
            turn=turn,
            usage=usage,
            streamed=streamed,
            control_plane=runner.control_plane,
        )

    if not streamed.saw_usage:
        await _emit_estimated_usage(runner, messages, turn=turn, usage=usage, streamed=streamed)

    await runner.control_plane.emit(
        "turn_completed",
        {"turn": turn, "had_tool_calls": bool(streamed.pending_calls)},
    )
    return streamed


async def dispatch_stream_event(
    event: StreamEvent,
    *,
    turn: int,
    usage: UsageTotals,
    streamed: StreamedTurn,
    control_plane: Any,
) -> None:
    """Apply one provider event to stream state and the control plane."""
    if event.type == "text_delta" and event.delta:
        streamed.assistant_text += event.delta
        await control_plane.emit(
            "text_delta",
            {"turn": turn, "delta": event.delta},
        )
    elif event.type == "reasoning_delta" and event.delta:
        summary_index = event.content_index
        streamed.reasoning_texts[summary_index] = (
            streamed.reasoning_texts.get(summary_index, "") + event.delta
        )
        await control_plane.emit(
            "reasoning_delta",
            {
                "turn": turn,
                "summary_index": summary_index,
                "delta": event.delta,
                "text": streamed.reasoning_texts[summary_index],
            },
        )
    elif event.type == "toolcall_start":
        streamed.pending_calls[event.content_index] = PendingToolCall(
            id=event.tool_call_id or f"toolcall-{turn}-{event.content_index}",
            name=event.tool_name,
            metadata=dict(event.tool_call_metadata or {}),
        )
        await control_plane.emit(
            "tool_call_started",
            {
                "turn": turn,
                "tool_call_id": streamed.pending_calls[event.content_index].id,
                "tool_name": event.tool_name,
            },
        )
    elif event.type == "toolcall_delta" and event.delta:
        pending = streamed.pending_calls.setdefault(
            event.content_index,
            PendingToolCall(id=f"toolcall-{turn}-{event.content_index}"),
        )
        pending.arguments_json += event.delta
        await control_plane.emit(
            "tool_call_delta",
            {
                "turn": turn,
                "tool_call_id": pending.id,
                "delta": event.delta,
            },
        )
    elif event.type == "retry":
        if event.retry_resets_stream:
            streamed.assistant_text = ""
            streamed.reasoning_texts.clear()
            streamed.pending_calls.clear()
            usage.prompt_tokens -= streamed.attempt_usage.prompt_tokens
            usage.completion_tokens -= streamed.attempt_usage.completion_tokens
            usage.reasoning_tokens -= streamed.attempt_usage.reasoning_tokens
            usage.total_tokens -= streamed.attempt_usage.total_tokens
            streamed.attempt_usage = UsageTotals()
            streamed.saw_usage = False
            streamed.budget_tokens = streamed.estimated_message_tokens
        await control_plane.emit(
            "model_retry_scheduled",
            {
                "turn": turn,
                "retry_after": event.retry_after or 0.0,
                "attempt": event.retry_attempt or 1,
                "reason": event.retry_reason or "rate_limit",
                "resets_stream": event.retry_resets_stream,
            },
        )
    elif event.type == "usage":
        streamed.saw_usage = True
        usage.prompt_tokens += event.prompt_tokens or 0
        usage.completion_tokens += event.completion_tokens or 0
        usage.reasoning_tokens += event.reasoning_tokens or 0
        usage.total_tokens += event.total_tokens or 0
        streamed.attempt_usage.prompt_tokens += event.prompt_tokens or 0
        streamed.attempt_usage.completion_tokens += event.completion_tokens or 0
        streamed.attempt_usage.reasoning_tokens += event.reasoning_tokens or 0
        streamed.attempt_usage.total_tokens += event.total_tokens or 0
        streamed.budget_tokens = event.prompt_tokens or usage.total_tokens
        await control_plane.emit(
            "usage",
            {
                "turn": turn,
                "prompt_tokens": event.prompt_tokens or 0,
                "completion_tokens": event.completion_tokens or 0,
                "reasoning_tokens": event.reasoning_tokens or 0,
                "total_tokens": event.total_tokens or 0,
                "cumulative_tokens": usage.total_tokens,
                "estimated": False,
            },
        )


async def _emit_estimated_usage(
    runner: TurnStreamHost,
    messages: List[Message],
    *,
    turn: int,
    usage: UsageTotals,
    streamed: StreamedTurn,
) -> None:
    prompt_tokens = estimate_prompt_tokens(messages)
    tool_arguments_json = "".join(
        pending.arguments_json for pending in streamed.pending_calls.values()
    )
    completion_tokens = estimate_completion_tokens(
        streamed.assistant_text,
        tool_arguments_json=tool_arguments_json,
    )
    total_tokens = prompt_tokens + completion_tokens
    usage.prompt_tokens += prompt_tokens
    usage.completion_tokens += completion_tokens
    usage.total_tokens += total_tokens
    streamed.budget_tokens = prompt_tokens
    await runner.control_plane.emit(
        "usage",
        {
            "turn": turn,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cumulative_tokens": usage.total_tokens,
            "estimated": True,
        },
    )


async def iter_provider_events(
    runner: TurnStreamHost,
    messages: List[Message],
) -> AsyncIterator[StreamEvent]:
    stream_options: Dict[str, Any] = {}
    if runner.reasoning_effort is not None:
        stream_options["reasoning_effort"] = runner.reasoning_effort
    agen = runner.registry.stream(
        runner.model_id,
        messages_for_model(
            messages,
            keep_recent=runner.tool_result_keep_recent,
            prune_tokens=runner.tool_result_prune_tokens,
        ),
        runner.tool_schemas,
        **stream_options,
    )
    closed = False

    async def close_stream() -> None:
        nonlocal closed
        if closed:
            return
        closed = True
        try:
            await agen.aclose()
        except RuntimeError:
            pass

    async def settle(task: Optional[asyncio.Task]) -> None:
        if task is None:
            return
        if not task.done():
            task.cancel()
        owner = asyncio.current_task()
        cancellations = owner.cancelling() if owner is not None else 0
        try:
            await task
        except asyncio.CancelledError:
            # Ignore cancellation of the helper, but never swallow a new
            # cancellation of the agent while it is cleaning up that helper.
            if owner is not None and owner.cancelling() > cancellations:
                raise
        except (StopAsyncIteration, RuntimeError):
            pass

    next_event: Optional[asyncio.Task] = None
    cancel_wait: Optional[asyncio.Task] = None
    try:
        while True:
            runner._raise_if_cancelled()
            runner._raise_if_runtime_exceeded()
            cancel_event = getattr(runner.control_plane, "cancel_event", None)
            next_event = asyncio.create_task(agen.__anext__())
            waiters = {next_event}
            cancel_wait = None
            if cancel_event is not None and not cancel_event.is_set():
                cancel_wait = asyncio.create_task(cancel_event.wait())
                waiters.add(cancel_wait)
            timeout = runner._remaining_runtime()
            if timeout is not None:
                timeout = max(timeout, 0.0)
            done, _pending = await asyncio.wait(
                waiters,
                return_when=asyncio.FIRST_COMPLETED,
                timeout=None if timeout is None else timeout,
            )
            actually_cancelled = runner._cancelled() or (
                cancel_event is not None and cancel_event.is_set()
            )
            if actually_cancelled:
                await settle(next_event)
                await settle(cancel_wait)
                next_event = None
                cancel_wait = None
                await close_stream()
                raise HarnessCancelled(runner._cancel_reason())
            if next_event not in done:
                wait_timeout = runner._remaining_runtime()
                more, _ = await asyncio.wait(
                    {next_event},
                    timeout=None if wait_timeout is None else max(wait_timeout, 0.0),
                )
                if not more:
                    await settle(next_event)
                    await settle(cancel_wait)
                    next_event = None
                    cancel_wait = None
                    await close_stream()
                    raise runner._runtime_exceeded_error()
            await settle(cancel_wait)
            cancel_wait = None
            try:
                event = next_event.result()
            except StopAsyncIteration:
                next_event = None
                break
            except asyncio.CancelledError:
                await close_stream()
                raise HarnessCancelled(runner._cancel_reason()) from None
            next_event = None
            yield event
    finally:
        await settle(next_event)
        await settle(cancel_wait)
        await close_stream()
