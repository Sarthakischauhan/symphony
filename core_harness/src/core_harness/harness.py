import json
from typing import Any, Dict, List, Optional

from core_ai.registry import ModelRegistry
from core_ai.types import Message

from core_harness.control_plane import ControlPlane, NullControlPlane
from core_harness.models.harness import HarnessResult
from core_harness.models.tools import PendingToolCall, ToolCall
from core_harness.tools import Tool


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
    ) -> None:
        self.registry = registry
        self.model_id = model_id
        self.system_prompt = system_prompt
        self.control_plane = control_plane or NullControlPlane()
        self.max_turns = max_turns
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
        for turn in range(self.max_turns):
            assistant_text = ""
            pending_calls: Dict[int, PendingToolCall] = {}

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

            if not pending_calls:
                messages.append(Message(role="assistant", content=assistant_text))
                await self.control_plane.emit(
                    "run_completed",
                    {"turn": turn, "output_text": assistant_text},
                )
                return HarnessResult(
                    output_text=assistant_text,
                    messages=messages,
                    tool_calls=all_tool_calls,
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

        raise RuntimeError(f"Harness exceeded max_turns={self.max_turns}")

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
