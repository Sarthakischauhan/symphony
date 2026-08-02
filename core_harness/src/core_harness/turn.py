"""Execution of one model turn, including streamed events and tool calls."""

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core_ai.registry import ModelRegistry
from core_ai.types import Message

from core_harness.control_plane import ControlPlane
from core_harness.models.harness import UsageTotals
from core_harness.models.tools import PendingToolCall, ToolCall
from core_harness.state import HarnessState
from core_harness.tokens import (
    estimate_completion_tokens,
    estimate_prompt_tokens,
    message_size_breakdown,
)
from core_harness.tools import Tool


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
        tool_schemas: List[Dict[str, Any]],
        tools: Dict[str, Tool],
        control_plane: ControlPlane,
        state: HarnessState,
        context_limit: Optional[int],
    ) -> None:
        self.registry = registry
        self.model_id = model_id
        self.tool_schemas = tool_schemas
        self.tools = tools
        self.control_plane = control_plane
        self.state = state
        self.context_limit = context_limit

    async def run(
        self,
        messages: List[Message],
        *,
        turn: int,
        usage: UsageTotals,
        context_left: Optional[int],
    ) -> TurnResult:
        """Process one turn and mutate ``messages`` with its results."""
        budget_tokens = usage.total_tokens
        compact_tokens_used = budget_tokens
        compact_context_left = context_left
        if compact_context_left is None and self.context_limit is not None:
            compact_tokens_used = estimate_prompt_tokens(messages)
            compact_context_left = max(self.context_limit - compact_tokens_used, 0)

        messages[:] = await self.state.maybe_compact(
            messages,
            turn=turn,
            context_limit=self.context_limit,
            tokens_used=compact_tokens_used,
            context_left=compact_context_left,
            emit=self.control_plane.emit,
        )
        await self.control_plane.emit(
            "turn_started",
            {"turn": turn, "message_count": len(messages)},
        )

        assistant_text = ""
        pending_calls: Dict[int, PendingToolCall] = {}
        saw_usage = False
        async for event in self.registry.stream(
            self.model_id,
            messages,
            self.tool_schemas,
        ):
            if event.type == "text_delta" and event.delta:
                assistant_text += event.delta
                await self.control_plane.emit(
                    "text_delta",
                    {"turn": turn, "delta": event.delta},
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
            elif event.type == "usage":
                saw_usage = True
                usage.prompt_tokens += event.prompt_tokens or 0
                usage.completion_tokens += event.completion_tokens or 0
                usage.total_tokens += event.total_tokens or 0
                budget_tokens = event.prompt_tokens or usage.total_tokens
                await self.control_plane.emit(
                    "usage",
                    {
                        "turn": turn,
                        "prompt_tokens": event.prompt_tokens or 0,
                        "completion_tokens": event.completion_tokens or 0,
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
            for tool_call in tool_calls:
                result = await self._execute_tool(tool_call)
                self.state.add_tool_message(
                    messages,
                    tool_call,
                    self._stringify_tool_output(result),
                )
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
            if not pending.arguments_json.strip():
                arguments = {}
            else:
                try:
                    arguments = json.loads(pending.arguments_json)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Invalid tool arguments: {pending.arguments_json}"
                    ) from exc
            if not isinstance(arguments, dict):
                raise ValueError("Tool arguments must decode to a JSON object.")
            tool_calls.append(
                ToolCall(
                    id=pending.id,
                    name=pending.name or "unknown_tool",
                    arguments=arguments,
                )
            )
        return tool_calls

    async def _execute_tool(self, tool_call: ToolCall) -> Any:
        if tool_call.name not in self.tools:
            raise KeyError(f"Tool '{tool_call.name}' is not registered.")
        await self.control_plane.emit(
            "tool_execution_started",
            {
                "tool_call_id": tool_call.id,
                "tool_name": tool_call.name,
                "arguments": tool_call.arguments,
            },
        )
        result = await self.tools[tool_call.name].execute(
            control_plane=self.control_plane,
            args=tool_call.arguments,
        )
        await self.control_plane.emit(
            "tool_execution_completed",
            {
                "tool_call_id": tool_call.id,
                "tool_name": tool_call.name,
                "result": self._stringify_tool_output(result),
            },
        )
        return result

    def _stringify_tool_output(self, value: Any) -> str:
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value)
        except TypeError:
            return str(value)


__all__ = ["TurnResult", "TurnRunner"]
