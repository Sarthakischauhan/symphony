import json
from typing import Any, Dict, List, Optional

from core_ai.registry import ModelRegistry
from core_ai.types import Message

from core_harness.control_plane import ControlPlane, NullControlPlane
from core_harness.models.harness import HarnessResult, UsageTotals
from core_harness.models.tools import PendingToolCall, ToolCall
from core_harness.tools import Tool


DEFAULT_CONTEXT_LIMITS = {
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4.1": 1047576,
    "gpt-4.1-mini": 1047576,
    "gpt-4.1-nano": 1047576,
}


class CoreHarness:
    def __init__(
        self,
        *,
        registry: ModelRegistry,
        model_id: str,
        system_prompt: str,
        tools: Optional[List[Tool]] = None,
        control_plane: Optional[ControlPlane] = None,
        max_turns: int = 8,
        context_limits: Optional[Dict[str, int]] = None,
    ) -> None:
        self.registry = registry
        self.model_id = model_id
        self.system_prompt = system_prompt
        self.control_plane = control_plane or NullControlPlane()
        self.max_turns = max_turns
        self.context_limits = {**DEFAULT_CONTEXT_LIMITS, **(context_limits or {})}
        self.tools: Dict[str, Tool] = {}

        for tool in tools or []:
            self.register_tool(tool)

    def register_tool(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def tool_schemas(self) -> List[Dict[str, Any]]:
        return [tool.get_schema() for tool in self.tools.values()]

    async def run(
        self,
        user_input: str,
        *,
        conversation: Optional[List[Message]] = None,
    ) -> HarnessResult:
        messages = [Message(role="system", content=self.system_prompt)]
        if conversation:
            messages.extend(conversation)
        messages.append(Message(role="user", content=user_input))

        await self.control_plane.emit(
            "run_started",
            {"model_id": self.model_id, "tool_names": list(self.tools)},
        )

        all_tool_calls: List[ToolCall] = []
        usage = UsageTotals()
        context_limit = self._context_limit()
        context_left: Optional[int] = None
        for turn in range(self.max_turns):
            assistant_text = ""
            pending_calls: Dict[int, PendingToolCall] = {}
            budget_tokens = usage.total_tokens

            await self.control_plane.emit(
                "turn_started",
                {"turn": turn, "message_count": len(messages)},
            )

            async for event in self.registry.stream(
                self.model_id,
                messages,
                self.tool_schemas(),
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
                elif event.type == "usage":
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
                        },
                    )

            await self.control_plane.emit(
                "turn_completed",
                {"turn": turn, "had_tool_calls": bool(pending_calls)},
            )
            context_left = (
                max(context_limit - budget_tokens, 0)
                if context_limit is not None
                else None
            )
            await self.control_plane.emit(
                "context",
                {
                    "turn": turn,
                    "context_limit": context_limit,
                    "tokens_used": budget_tokens,
                    "context_left": context_left,
                    "utilization": (
                        budget_tokens / context_limit if context_limit else None
                    ),
                },
            )

            if not pending_calls:
                messages.append(Message(role="assistant", content=assistant_text))
                await self.control_plane.emit(
                    "run_completed",
                    {
                        "turn": turn,
                        "output_text": assistant_text,
                        "usage": usage.model_dump(),
                        "context": {
                            "context_limit": context_limit,
                            "tokens_used": budget_tokens,
                            "context_left": context_left,
                            "utilization": (
                                budget_tokens / context_limit if context_limit else None
                            ),
                        },
                    },
                )
                return HarnessResult(
                    output_text=assistant_text,
                    messages=messages,
                    tool_calls=all_tool_calls,
                    usage=usage,
                    context_limit=context_limit,
                    context_left=context_left,
                )

            tool_calls = self._build_tool_calls(pending_calls)
            all_tool_calls.extend(tool_calls)
            messages.append(
                Message(
                    role="assistant",
                    content=assistant_text,
                    tool_calls=[self._to_message_tool_call(tool_call) for tool_call in tool_calls],
                )
            )

            for tool_call in tool_calls:
                tool_output = await self._execute_tool(tool_call)
                messages.append(
                    Message(
                        role="tool",
                        content=self._stringify_tool_output(tool_output),
                        tool_call_id=tool_call.id,
                    )
                )

        await self.control_plane.emit(
            "run_failed",
            {
                "turn": self.max_turns - 1,
                "error_type": "RuntimeError",
                "message": f"Harness exceeded max_turns={self.max_turns}",
            },
        )
        raise RuntimeError(f"Harness exceeded max_turns={self.max_turns}")

    def _context_limit(self) -> Optional[int]:
        if self.model_id in self.context_limits:
            return self.context_limits[self.model_id]

        model_name = self.model_id.split(":", 1)[-1]
        if model_name in self.context_limits:
            return self.context_limits[model_name]

        for known_model, limit in sorted(
            self.context_limits.items(), key=lambda item: len(item[0]), reverse=True
        ):
            if model_name.startswith(f"{known_model}-"):
                return limit

        return None

    def _build_tool_calls(
        self,
        pending_calls: Dict[int, PendingToolCall],
    ) -> List[ToolCall]:
        tool_calls: List[ToolCall] = []

        for pending in pending_calls.values():
            tool_calls.append(
                ToolCall(
                    id=pending.id,
                    name=pending.name or "unknown_tool",
                    arguments=self._decode_tool_arguments(pending.arguments_json),
                )
            )

        return tool_calls

    def _decode_tool_arguments(self, raw_arguments: str) -> Dict[str, Any]:
        if not raw_arguments.strip():
            return {}

        try:
            decoded = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid tool arguments: {raw_arguments}") from exc

        if not isinstance(decoded, dict):
            raise ValueError("Tool arguments must decode to a JSON object.")

        return decoded

    def _to_message_tool_call(self, tool_call: ToolCall) -> Dict[str, Any]:
        return {
            "id": tool_call.id,
            "type": "function",
            "function": {
                "name": tool_call.name,
                "arguments": json.dumps(tool_call.arguments),
            },
        }

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
