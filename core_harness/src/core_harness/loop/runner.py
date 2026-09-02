"""Execution of one model turn, including streamed events and tool calls."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from core_ai.registry import ModelRegistry
from core_ai.types import Message

from core_harness.events import ControlPlane
from core_harness.errors import HarnessCancelled, HarnessLimitExceeded
from core_harness.models import UsageTotals
from core_harness.models import ToolCall
from core_harness.context import (
    HarnessState,
    estimate_prompt_tokens,
    message_size_breakdown,
)
from core_harness.tools import Tool
from core_harness.loop.calls import build_tool_calls, run_tool_calls
from core_harness.loop.stream import stream_model_turn


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


class TurnRunner:
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
        estimated_message_tokens = await self.maybe_compact_turn(
            messages,
            turn=turn,
            context_left=context_left,
        )
        await self.control_plane.emit(
            "turn_started",
            {"turn": turn, "message_count": len(messages)},
        )

        streamed = await stream_model_turn(
            self,
            messages,
            turn=turn,
            usage=usage,
            estimated_message_tokens=estimated_message_tokens,
        )
        context_left, message_sizes = await self.emit_context(
            messages,
            turn=turn,
            budget_tokens=streamed.budget_tokens,
            estimated_message_tokens=estimated_message_tokens,
        )
        await self.maybe_emit_context_warning(
            turn=turn,
            tokens_used=streamed.budget_tokens,
            context_left=context_left,
        )

        tool_calls = build_tool_calls(streamed.pending_calls)
        if tool_calls:
            self.state.add_assistant_message(messages, streamed.assistant_text, tool_calls)
            await run_tool_calls(self, messages, tool_calls)
        else:
            self.state.add_assistant_message(messages, streamed.assistant_text)

        return TurnResult(
            assistant_text=streamed.assistant_text,
            tool_calls=tool_calls,
            usage=usage,
            budget_tokens=streamed.budget_tokens,
            context_left=context_left,
            message_sizes=message_sizes,
        )

    async def maybe_compact_turn(
        self,
        messages: List[Message],
        *,
        turn: int,
        context_left: Optional[int],
    ) -> int:
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
        return estimate_prompt_tokens(messages)

    async def emit_context(
        self,
        messages: List[Message],
        *,
        turn: int,
        budget_tokens: int,
        estimated_message_tokens: int,
    ) -> tuple[Optional[int], List[Dict[str, Any]]]:
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
        return context_left, message_sizes

    async def maybe_emit_context_warning(
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
