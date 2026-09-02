"""Execution of one model turn, including streamed events and tool calls."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from core_ai.registry import ModelRegistry
from core_ai.types import Message

from core_harness.events import ControlPlane
from core_harness.errors import HarnessCancelled, HarnessLimitExceeded
from core_harness.models import UsageTotals
from core_harness.models import PendingToolCall, ToolCall
from core_harness.context import (
    HarnessState,
    estimate_completion_tokens,
    estimate_prompt_tokens,
    message_size_breakdown,
    messages_for_model,
)
from core_harness.tools import Tool
from core_harness.loop.calls import TurnToolCalls


async def _ignore_addon_hook(_hook: str, **_payload: Any) -> None:
    return None


@dataclass
class TurnResult:
    """Output produced after one model/tool turn completes."""

    assistant_text: str
    tool_calls: List[ToolCall]
    usage: UsageTotals
    budget_tokens: int
    context_left: Optional[int]
    message_sizes: List[Dict[str, Any]]


class TurnRunner(TurnToolCalls):
    """Owns provider event handling and tool execution for one turn."""

    def __init__(
        self,
        *,
        registry: ModelRegistry,
        model_id: str,
        reasoning_effort: Optional[str] = None,
        tool_schemas: List[Dict[str, Any]],
        tools: Dict[str, Tool],
        control_plane: ControlPlane,
        state: HarnessState,
        context_limit: Optional[int],
        tool_result_max_chars: Optional[int],
        tool_result_keep_recent: int = 8,
        tool_result_prune_tokens: Optional[int] = None,
        context_target_tokens: Optional[int],
        remaining_runtime: Optional[float] = None,
        max_tool_calls: Optional[int] = None,
        tool_calls_so_far: int = 0,
        deadline: Optional[float] = None,
        max_runtime_seconds: Optional[float] = None,
        max_parallel_tool_calls: int = 1,
        notify_addons: Optional[Callable[..., Awaitable[None]]] = None,
    ) -> None:
        self.registry = registry
        self.model_id = model_id
        self.reasoning_effort = reasoning_effort
        self.tool_schemas = tool_schemas
        self.tools = tools
        self.control_plane = control_plane
        self.state = state
        self.context_limit = context_limit
        self.tool_result_max_chars = tool_result_max_chars
        self.tool_result_keep_recent = tool_result_keep_recent
        self.tool_result_prune_tokens = tool_result_prune_tokens
        self.context_target_tokens = context_target_tokens
        self.remaining_runtime = remaining_runtime
        self.max_tool_calls = max_tool_calls
        self.tool_calls_so_far = tool_calls_so_far
        self.deadline = deadline
        self.max_runtime_seconds = max_runtime_seconds
        self.max_parallel_tool_calls = max_parallel_tool_calls
        self.notify_addons = notify_addons or _ignore_addon_hook

    def _cancelled(self) -> bool:
        return bool(getattr(self.control_plane, "cancelled", False))

    def _cancel_reason(self) -> str:
        return str(getattr(self.control_plane, "cancel_reason", "cancelled"))

    def _raise_if_cancelled(self) -> None:
        if self._cancelled():
            raise HarnessCancelled(self._cancel_reason())

    def _remaining_runtime(self) -> Optional[float]:
        if self.deadline is not None:
            return self.deadline - time.monotonic()
        return self.remaining_runtime

    def _runtime_exceeded_error(self) -> HarnessLimitExceeded:
        elapsed = None
        if self.deadline is not None and self.max_runtime_seconds is not None:
            elapsed = self.max_runtime_seconds - max(self._remaining_runtime() or 0.0, 0.0)
        return HarnessLimitExceeded(
            "max_runtime_seconds",
            float(elapsed if elapsed is not None else 0.0),
            float(self.max_runtime_seconds or 0.0),
            f"Harness exceeded max_runtime_seconds={self.max_runtime_seconds}",
        )

    def _raise_if_runtime_exceeded(self) -> None:
        remaining = self._remaining_runtime()
        if remaining is not None and remaining <= 0:
            raise self._runtime_exceeded_error()

    async def run(
        self,
        messages: List[Message],
        *,
        turn: int,
        usage: UsageTotals,
        context_left: Optional[int],
    ) -> TurnResult:
        """Process one turn and mutate ``messages`` with its results."""
        self._raise_if_cancelled()
        estimated_message_tokens = estimate_prompt_tokens(messages)
        previous_request_tokens = (
            self.context_limit - context_left
            if self.context_limit is not None and context_left is not None
            else 0
        )
        compact_tokens_used = max(estimated_message_tokens, previous_request_tokens)
        compact_context_left = (
            max(self.context_limit - compact_tokens_used, 0)
            if self.context_limit is not None
            else None
        )

        compacted = await self.state.maybe_compact(
            messages,
            turn=turn,
            context_limit=self.context_limit,
            tokens_used=compact_tokens_used,
            context_left=compact_context_left,
            emit=self.control_plane.emit,
        )
        if compacted is not messages:
            await self.notify_addons(
                "on_compact",
                turn=turn,
                messages=compacted,
                context_limit=self.context_limit,
                tokens_used=compact_tokens_used,
                context_left=compact_context_left,
            )
        messages[:] = compacted
        estimated_message_tokens = estimate_prompt_tokens(messages)
        budget_tokens = estimated_message_tokens
        await self.control_plane.emit(
            "turn_started",
            {"turn": turn, "message_count": len(messages)},
        )

        assistant_text = ""
        reasoning_texts: Dict[int, str] = {}
        pending_calls: Dict[int, PendingToolCall] = {}
        saw_usage = False
        attempt_usage = UsageTotals()
        async for event in self._stream_events(messages):
            if event.type == "text_delta" and event.delta:
                assistant_text += event.delta
                await self.control_plane.emit(
                    "text_delta",
                    {"turn": turn, "delta": event.delta},
                )
            elif event.type == "reasoning_delta" and event.delta:
                summary_index = event.content_index
                reasoning_texts[summary_index] = (
                    reasoning_texts.get(summary_index, "") + event.delta
                )
                await self.control_plane.emit(
                    "reasoning_delta",
                    {
                        "turn": turn,
                        "summary_index": summary_index,
                        "delta": event.delta,
                        "text": reasoning_texts[summary_index],
                    },
                )
            elif event.type == "toolcall_start":
                pending_calls[event.content_index] = PendingToolCall(
                    id=event.tool_call_id or f"toolcall-{turn}-{event.content_index}",
                    name=event.tool_name,
                )
                await self.control_plane.emit(
                    "tool_call_started",
                    {
                        "turn": turn,
                        "tool_call_id": pending_calls[event.content_index].id,
                        "tool_name": event.tool_name,
                    },
                )
            elif event.type == "toolcall_delta" and event.delta:
                pending = pending_calls.setdefault(
                    event.content_index,
                    PendingToolCall(id=f"toolcall-{turn}-{event.content_index}"),
                )
                pending.arguments_json += event.delta
                await self.control_plane.emit(
                    "tool_call_delta",
                    {
                        "turn": turn,
                        "tool_call_id": pending.id,
                        "delta": event.delta,
                    },
                )
            elif event.type == "retry":
                if event.retry_resets_stream:
                    assistant_text = ""
                    reasoning_texts.clear()
                    pending_calls.clear()
                    usage.prompt_tokens -= attempt_usage.prompt_tokens
                    usage.completion_tokens -= attempt_usage.completion_tokens
                    usage.reasoning_tokens -= attempt_usage.reasoning_tokens
                    usage.total_tokens -= attempt_usage.total_tokens
                    attempt_usage = UsageTotals()
                    saw_usage = False
                    budget_tokens = estimated_message_tokens
                await self.control_plane.emit(
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
                saw_usage = True
                usage.prompt_tokens += event.prompt_tokens or 0
                usage.completion_tokens += event.completion_tokens or 0
                usage.reasoning_tokens += event.reasoning_tokens or 0
                usage.total_tokens += event.total_tokens or 0
                attempt_usage.prompt_tokens += event.prompt_tokens or 0
                attempt_usage.completion_tokens += event.completion_tokens or 0
                attempt_usage.reasoning_tokens += event.reasoning_tokens or 0
                attempt_usage.total_tokens += event.total_tokens or 0
                budget_tokens = event.prompt_tokens or usage.total_tokens
                await self.control_plane.emit(
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

        if not saw_usage:
            prompt_tokens = estimate_prompt_tokens(messages)
            tool_arguments_json = "".join(
                pending.arguments_json for pending in pending_calls.values()
            )
            completion_tokens = estimate_completion_tokens(
                assistant_text,
                tool_arguments_json=tool_arguments_json,
            )
            total_tokens = prompt_tokens + completion_tokens
            usage.prompt_tokens += prompt_tokens
            usage.completion_tokens += completion_tokens
            usage.total_tokens += total_tokens
            budget_tokens = prompt_tokens
            await self.control_plane.emit(
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

        await self.control_plane.emit(
            "turn_completed",
            {"turn": turn, "had_tool_calls": bool(pending_calls)},
        )
        message_sizes = message_size_breakdown(messages)
        context_left = (
            max(self.context_limit - budget_tokens, 0)
            if self.context_limit is not None
            else None
        )
        await self.control_plane.emit(
            "context",
            {
                "turn": turn,
                "context_limit": self.context_limit,
                "tokens_used": budget_tokens,
                "estimated_message_tokens": estimated_message_tokens,
                "context_left": context_left,
                "utilization": (
                    budget_tokens / self.context_limit if self.context_limit else None
                ),
                "message_sizes": message_sizes,
            },
        )
        await self._maybe_emit_context_warning(
            turn=turn,
            tokens_used=budget_tokens,
            context_left=context_left,
        )

        tool_calls = self._build_tool_calls(pending_calls)
        if tool_calls:
            self.state.add_assistant_message(messages, assistant_text, tool_calls)
            await self._run_tool_calls(messages, tool_calls)
        else:
            self.state.add_assistant_message(messages, assistant_text)

        return TurnResult(
            assistant_text=assistant_text,
            tool_calls=tool_calls,
            usage=usage,
            budget_tokens=budget_tokens,
            context_left=context_left,
            message_sizes=message_sizes,
        )


    async def _stream_events(self, messages: List[Message]):
        stream_options: Dict[str, Any] = {}
        if self.reasoning_effort is not None:
            stream_options["reasoning_effort"] = self.reasoning_effort
        agen = self.registry.stream(
            self.model_id,
            messages_for_model(
                messages,
                keep_recent=self.tool_result_keep_recent,
                prune_tokens=self.tool_result_prune_tokens,
            ),
            self.tool_schemas,
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
            try:
                await task
            except (asyncio.CancelledError, StopAsyncIteration, RuntimeError):
                pass

        next_event: Optional[asyncio.Task] = None
        cancel_wait: Optional[asyncio.Task] = None
        try:
            while True:
                self._raise_if_cancelled()
                self._raise_if_runtime_exceeded()
                cancel_event = getattr(self.control_plane, "cancel_event", None)
                next_event = asyncio.create_task(agen.__anext__())
                waiters = {next_event}
                cancel_wait = None
                if cancel_event is not None and not cancel_event.is_set():
                    cancel_wait = asyncio.create_task(cancel_event.wait())
                    waiters.add(cancel_wait)
                timeout = self._remaining_runtime()
                if timeout is not None:
                    timeout = max(timeout, 0.0)
                done, _pending = await asyncio.wait(
                    waiters,
                    return_when=asyncio.FIRST_COMPLETED,
                    timeout=None if timeout is None else timeout,
                )
                actually_cancelled = self._cancelled() or (
                    cancel_event is not None and cancel_event.is_set()
                )
                if actually_cancelled:
                    await settle(next_event)
                    await settle(cancel_wait)
                    next_event = None
                    cancel_wait = None
                    await close_stream()
                    raise HarnessCancelled(self._cancel_reason())
                if next_event not in done:
                    wait_timeout = self._remaining_runtime()
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
                        raise self._runtime_exceeded_error()
                await settle(cancel_wait)
                cancel_wait = None
                try:
                    event = next_event.result()
                except StopAsyncIteration:
                    next_event = None
                    break
                except asyncio.CancelledError:
                    await close_stream()
                    raise HarnessCancelled(self._cancel_reason()) from None
                next_event = None
                yield event
        finally:
            await settle(next_event)
            await settle(cancel_wait)
            await close_stream()

    async def _maybe_emit_context_warning(
        self,
        *,
        turn: int,
        tokens_used: int,
        context_left: Optional[int],
    ) -> None:
        if not self.state.should_warn(context_left):
            return
        await self.control_plane.emit(
            "context_warning",
            {
                "turn": turn,
                "context_limit": self.context_limit,
                "tokens_used": tokens_used,
                "context_left": context_left,
                "threshold": self.state.context_warn_threshold,
            },
        )

    def _build_tool_calls(
        self,
        pending_calls: Dict[int, PendingToolCall],
    ) -> List[ToolCall]:
        tool_calls: List[ToolCall] = []
        for pending in pending_calls.values():
            decode_error: Optional[str] = None
            arguments: Dict[str, Any] = {}
            raw = pending.arguments_json.strip()
            if raw:
                try:
                    decoded = json.loads(pending.arguments_json)
                except json.JSONDecodeError as exc:
                    decode_error = f"Invalid tool arguments: {pending.arguments_json} ({exc})"
                    decoded = {}
                if decode_error is None and not isinstance(decoded, dict):
                    decode_error = "Tool arguments must decode to a JSON object."
                    decoded = {}
                arguments = decoded if isinstance(decoded, dict) else {}
            call = ToolCall(
                id=pending.id,
                name=pending.name or "unknown_tool",
                arguments=arguments,
            )
            if decode_error:
                call.result_status = "error"
                call.arguments["_decode_error"] = decode_error
            tool_calls.append(call)
        return tool_calls
