import json
import uuid
from typing import Any, Dict, List, Optional

from core_ai.registry import ModelRegistry
from core_ai.types import Message

from core_harness.control_plane import ControlPlane, NullControlPlane
from core_harness.models.control_plane import ControlCommandType
from core_harness.models.harness import HarnessResult, UsageTotals
from core_harness.models.tools import PendingToolCall, ToolCall
from core_harness.state import Compactor, HarnessState
from core_harness.persistence import Checkpoint, NullPersistence, Persistence
from core_harness.tokens import (
    estimate_completion_tokens,
    estimate_prompt_tokens,
    message_size_breakdown,
)
from core_harness.tools import Tool


class HarnessCancelled(RuntimeError):
    """Raised when an inbound cancel command stops the harness run."""


class CoreHarness:
    def __init__(
        self,
        *,
        registry: ModelRegistry,
        model_id: str,
        system_prompt: str,
        tools: Optional[List[Tool]] = None,
        control_plane: Optional[ControlPlane] = None,
        persistence: Optional[Persistence] = None,
        session_id: Optional[str] = None,
        max_turns: int = 8,
        context_limits: Optional[Dict[str, int]] = None,
        context_warn_threshold: Optional[int] = None,
        context_compact_threshold: Optional[int] = None,
        compactor: Optional[Compactor] = None,
    ) -> None:
        self.registry = registry
        self.model_id = model_id
        self.system_prompt = system_prompt
        self.control_plane = control_plane or NullControlPlane()
        self.persistence = persistence or NullPersistence()
        self.session_id = session_id
        self.max_turns = max_turns
        self.state = HarnessState(
            context_limits=context_limits,
            context_warn_threshold=context_warn_threshold,
            context_compact_threshold=context_compact_threshold,
            compactor=compactor,
        )
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
        session_id: Optional[str] = None,
    ) -> HarnessResult:
        active_session = session_id or self.session_id or str(uuid.uuid4())

        prior = conversation
        if prior is None:
            loaded = await self.persistence.load_conversation(session_id=active_session)
            # Drop stored system messages; harness always prepends the live system prompt.
            prior = [message for message in loaded if message.role != "system"] or None

        messages = [Message(role="system", content=self.system_prompt)]
        if prior:
            messages.extend(prior)
        messages.append(Message(role="user", content=user_input))

        await self.control_plane.emit(
            "run_started",
            {
                "model_id": self.model_id,
                "tool_names": list(self.tools),
                "session_id": active_session,
            },
        )
        await self._persist_conversation(active_session, messages)

        all_tool_calls: List[ToolCall] = []
        usage = UsageTotals()
        context_limit = self.state.context_limit(self.model_id)
        context_left: Optional[int] = None
        budget_tokens = 0
        current_turn = 0
        try:
            for turn in range(self.max_turns):
                current_turn = turn
                messages = await self._apply_inbound_commands(messages, turn=turn)

                assistant_text = ""
                pending_calls: Dict[int, PendingToolCall] = {}
                saw_usage = False
                budget_tokens = usage.total_tokens
                compact_tokens_used = budget_tokens
                compact_context_left = context_left
                if compact_context_left is None and context_limit is not None:
                    compact_tokens_used = estimate_prompt_tokens(messages)
                    compact_context_left = max(context_limit - compact_tokens_used, 0)

                messages = await self.state.maybe_compact(
                    messages,
                    turn=turn,
                    context_limit=context_limit,
                    tokens_used=compact_tokens_used,
                    context_left=compact_context_left,
                    emit=self.control_plane.emit,
                )

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
                        "message_sizes": message_sizes,
                    },
                )
                await self._maybe_emit_context_warning(
                    turn=turn,
                    context_limit=context_limit,
                    tokens_used=budget_tokens,
                    context_left=context_left,
                )

                if not pending_calls:
                    messages.append(Message(role="assistant", content=assistant_text))
                    await self._persist_state(
                        session_id=active_session,
                        turn=turn,
                        messages=messages,
                        usage=usage,
                        context_limit=context_limit,
                        context_left=context_left,
                        status="completed",
                        metadata={"output_text": assistant_text},
                    )
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
                                "message_sizes": message_sizes,
                            },
                            "session_id": active_session,
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
                        tool_calls=[
                            self._to_message_tool_call(tool_call) for tool_call in tool_calls
                        ],
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

                await self._persist_state(
                    session_id=active_session,
                    turn=turn,
                    messages=messages,
                    usage=usage,
                    context_limit=context_limit,
                    context_left=context_left,
                    status="running",
                )
        except HarnessCancelled as exc:
            await self._persist_state(
                session_id=active_session,
                turn=current_turn,
                messages=messages,
                usage=usage,
                context_limit=context_limit,
                context_left=context_left,
                status="cancelled",
                metadata={"reason": str(exc)},
            )
            raise
        except Exception as exc:
            await self.control_plane.emit(
                "run_failed",
                {
                    "turn": current_turn,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
            )
            await self._persist_state(
                session_id=active_session,
                turn=current_turn,
                messages=messages,
                usage=usage,
                context_limit=context_limit,
                context_left=context_left,
                status="failed",
                metadata={"error_type": type(exc).__name__, "message": str(exc)},
            )
            raise

        await self.control_plane.emit(
            "run_failed",
            {
                "turn": self.max_turns - 1,
                "error_type": "RuntimeError",
                "message": f"Harness exceeded max_turns={self.max_turns}",
            },
        )
        await self._persist_state(
            session_id=active_session,
            turn=self.max_turns - 1,
            messages=messages,
            usage=usage,
            context_limit=context_limit,
            context_left=context_left,
            status="failed",
            metadata={"message": f"Harness exceeded max_turns={self.max_turns}"},
        )
        raise RuntimeError(f"Harness exceeded max_turns={self.max_turns}")

    async def _persist_conversation(
        self,
        session_id: str,
        messages: List[Message],
    ) -> None:
        await self.persistence.save_conversation(
            session_id=session_id,
            messages=list(messages),
        )

    async def _persist_state(
        self,
        *,
        session_id: str,
        turn: int,
        messages: List[Message],
        usage: UsageTotals,
        context_limit: Optional[int],
        context_left: Optional[int],
        status: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        await self._persist_conversation(session_id, messages)
        await self.persistence.save_checkpoint(
            checkpoint=Checkpoint(
                session_id=session_id,
                turn=turn,
                messages=list(messages),
                usage=usage.model_copy(deep=True),
                context_limit=context_limit,
                context_left=context_left,
                status=status,  # type: ignore[arg-type]
                metadata=metadata or {},
            )
        )

    async def _apply_inbound_commands(
        self,
        messages: List[Message],
        *,
        turn: int,
    ) -> List[Message]:
        wait_if_paused = getattr(self.control_plane, "wait_if_paused", None)
        if wait_if_paused is not None and getattr(self.control_plane, "paused", False):
            await self.control_plane.emit("paused", {"turn": turn})
            await wait_if_paused()
            await self.control_plane.emit("resumed", {"turn": turn})

        drain = getattr(self.control_plane, "drain_commands", None)
        if drain is None:
            return messages

        for command in await drain():
            if command.type == ControlCommandType.CANCEL:
                reason = str(command.payload.get("reason", "cancelled"))
                await self.control_plane.emit(
                    "run_cancelled",
                    {"turn": turn, "reason": reason},
                )
                raise HarnessCancelled(reason)
            if command.type == ControlCommandType.INJECT_MESSAGE:
                injected = command.to_message()
                messages.append(injected)
                await self.control_plane.emit(
                    "message_injected",
                    {
                        "turn": turn,
                        "role": injected.role,
                        "content": injected.content,
                    },
                )
        return messages

    async def _maybe_emit_context_warning(
        self,
        *,
        turn: int,
        context_limit: Optional[int],
        tokens_used: int,
        context_left: Optional[int],
    ) -> None:
        if not self.state.should_warn(context_left):
            return

        await self.control_plane.emit(
            "context_warning",
            {
                "turn": turn,
                "context_limit": context_limit,
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
