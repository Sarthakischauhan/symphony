"""Consume a provider stream into turn text, tool calls, and usage."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List

from core_ai.types import Message, StreamEvent

from core_harness.context import estimate_completion_tokens, estimate_prompt_tokens
from core_harness.models import PendingToolCall, StreamedTurn, UsageTotals


async def stream_model_turn(
    runner: Any,
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
            emit=runner.emit,
        )

    if not streamed.saw_usage:
        await _emit_estimated_usage(runner, messages, turn=turn, usage=usage, streamed=streamed)

    await runner.emit(
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
    emit: Callable[..., Awaitable[None]],
) -> None:
    """Apply one provider event to stream state and the event sink."""
    if event.type == "text_delta" and event.delta:
        streamed.assistant_text += event.delta
        await emit(
            "text_delta",
            {"turn": turn, "delta": event.delta},
        )
    elif event.type == "reasoning_delta" and event.delta:
        summary_index = event.content_index
        streamed.reasoning_texts[summary_index] = (
            streamed.reasoning_texts.get(summary_index, "") + event.delta
        )
        await emit(
            "reasoning_delta",
            {
                "turn": turn,
                "summary_index": summary_index,
                "delta": event.delta,
                "text": streamed.reasoning_texts[summary_index],
            },
        )
    elif event.type == "toolcall_start":
        # Some OpenAI-compatible streams split the id/name over multiple
        # deltas.  Do not replace a call created by an earlier argument delta:
        # doing so loses the accumulated arguments and the eventual tool
        # output is associated with a different id than the model's call.
        pending = streamed.pending_calls.get(event.content_index)
        if pending is None:
            pending = PendingToolCall(
                id=event.tool_call_id or f"toolcall-{turn}-{event.content_index}",
                name=event.tool_name,
                metadata=dict(event.tool_call_metadata or {}),
            )
            streamed.pending_calls[event.content_index] = pending
        else:
            if event.tool_call_id:
                pending.id = event.tool_call_id
            if event.tool_name:
                pending.name = event.tool_name
            if event.tool_call_metadata:
                pending.metadata.update(event.tool_call_metadata)
        await emit(
            "tool_call_started",
            {
                "turn": turn,
                "tool_call_id": pending.id,
                "tool_name": pending.name,
            },
        )
    elif event.type == "toolcall_delta" and event.delta:
        pending = streamed.pending_calls.setdefault(
            event.content_index,
            PendingToolCall(
                id=event.tool_call_id or f"toolcall-{turn}-{event.content_index}"
            ),
        )
        if event.tool_call_id and pending.id.startswith("toolcall-"):
            pending.id = event.tool_call_id
        pending.arguments_json += event.delta
        await emit(
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
        await emit(
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
        await emit(
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
    runner: Any,
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
    await runner.emit(
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
    runner: Any,
    messages: List[Message],
) -> AsyncIterator[StreamEvent]:
    stream_options: Dict[str, Any] = {}
    if runner.reasoning_effort is not None:
        stream_options["reasoning_effort"] = runner.reasoning_effort
    if getattr(runner, "session_id", None) and str(runner.model_id).startswith("grok:"):
        stream_options["extra_headers"] = {"x-grok-conv-id": runner.session_id}
    agen = runner.registry.stream(
        runner.model_id,
        messages,
        runner.tool_schemas,
        **stream_options,
    )
    try:
        while True:
            runner._raise_if_runtime_exceeded()
            timeout = runner._remaining_runtime()
            try:
                if timeout is None:
                    event = await agen.__anext__()
                else:
                    event = await asyncio.wait_for(
                        agen.__anext__(),
                        timeout=max(timeout, 0.0),
                    )
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                raise runner._runtime_exceeded_error() from None
            yield event
    finally:
        try:
            await agen.aclose()
        except RuntimeError:
            pass
