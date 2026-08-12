"""Session lifecycle, persistence, and terminal outcomes for one harness run."""

import uuid
from typing import Any, Dict, List, Optional

from core_ai.registry import ModelRegistry
from core_ai.types import Message

from core_harness.control_plane import ControlPlane
from core_harness.models.control_plane import ControlCommandType
from core_harness.models.harness import HarnessResult, UsageTotals
from core_harness.models.tools import ToolCall
from core_harness.persistence import Checkpoint, Persistence
from core_harness.state import HarnessState, normalize_tool_protocol
from core_harness.tools import Tool
from core_harness.turn import TurnRunner


class HarnessCancelled(RuntimeError):
    """Raised when an inbound cancel command stops the harness run."""


class HarnessRun:
    """Owns session setup, turn iteration, persistence, and run outcomes."""

    def __init__(
        self,
        *,
        registry: ModelRegistry,
        model_id: str,
        system_prompt: str,
        tools: Dict[str, Tool],
        tool_schemas: List[Dict[str, Any]],
        control_plane: ControlPlane,
        persistence: Persistence,
        default_session_id: Optional[str],
        max_turns: int,
        state: HarnessState,
        tool_result_max_chars: Optional[int],
        context_target_tokens: Optional[int],
    ) -> None:
        self.registry = registry
        self.model_id = model_id
        self.system_prompt = system_prompt
        self.tools = tools
        self.tool_schemas = tool_schemas
        self.control_plane = control_plane
        self.persistence = persistence
        self.default_session_id = default_session_id
        self.max_turns = max_turns
        self.state = state
        self.tool_result_max_chars = tool_result_max_chars
        self.context_target_tokens = context_target_tokens

    async def execute(
        self,
        user_input: str,
        *,
        conversation: Optional[List[Message]],
        session_id: Optional[str] = None,
    ) -> HarnessResult:
        active_session = session_id or self.default_session_id or str(uuid.uuid4())
        messages = await self._initial_messages(
            active_session,
            user_input,
            conversation,
        )
        await self.control_plane.emit(
            "run_started",
            {
                "model_id": self.model_id,
                "tool_names": list(self.tools),
                "session_id": active_session,
            },
        )
        await self._persist_conversation(active_session, messages)

        usage = UsageTotals()
        all_tool_calls: List[ToolCall] = []
        context_limit = self.state.context_limit(self.model_id)
        context_left: Optional[int] = None
        turn_runner = TurnRunner(
            registry=self.registry,
            model_id=self.model_id,
            tool_schemas=self.tool_schemas,
            tools=self.tools,
            control_plane=self.control_plane,
            state=self.state,
            context_limit=context_limit,
            tool_result_max_chars=self.tool_result_max_chars,
            context_target_tokens=self.context_target_tokens,
        )

        try:
            for turn in range(self.max_turns):
                messages = await self._apply_inbound_commands(messages, turn=turn)
                result = await turn_runner.run(
                    messages,
                    turn=turn,
                    usage=usage,
                    context_left=context_left,
                )
                context_left = result.context_left
                all_tool_calls.extend(result.tool_calls)

                if not result.tool_calls:
                    await self._persist_state(
                        session_id=active_session,
                        turn=turn,
                        messages=messages,
                        usage=usage,
                        context_limit=context_limit,
                        context_left=context_left,
                        status="completed",
                        metadata={"output_text": result.assistant_text},
                    )
                    await self.control_plane.emit(
                        "run_completed",
                        {
                            "turn": turn,
                            "output_text": result.assistant_text,
                            "usage": usage.model_dump(),
                            "context": {
                                "context_limit": context_limit,
                                "tokens_used": result.budget_tokens,
                                "context_left": context_left,
                                "utilization": (
                                    result.budget_tokens / context_limit
                                    if context_limit
                                    else None
                                ),
                                "message_sizes": result.message_sizes,
                            },
                            "session_id": active_session,
                        },
                    )
                    return HarnessResult(
                        output_text=result.assistant_text,
                        messages=messages,
                        tool_calls=all_tool_calls,
                        usage=usage,
                        context_limit=context_limit,
                        context_left=context_left,
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
                turn=turn,
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
                    "turn": turn,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
            )
            await self._persist_state(
                session_id=active_session,
                turn=turn,
                messages=messages,
                usage=usage,
                context_limit=context_limit,
                context_left=context_left,
                status="failed",
                metadata={"error_type": type(exc).__name__, "message": str(exc)},
            )
            raise

        message = f"Harness exceeded max_turns={self.max_turns}"
        await self.control_plane.emit(
            "run_failed",
            {
                "turn": self.max_turns - 1,
                "error_type": "RuntimeError",
                "message": message,
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
            metadata={"message": message},
        )
        raise RuntimeError(message)

    async def _initial_messages(
        self,
        session_id: str,
        user_input: str,
        conversation: Optional[List[Message]],
    ) -> List[Message]:
        prior = conversation
        if prior is None:
            loaded = await self.persistence.load_conversation(session_id=session_id)
            prior = [message for message in loaded if message.role != "system"]

        messages = [Message(role="system", content=self.system_prompt)]
        messages.extend(
            message
            for message in normalize_tool_protocol(prior or [])
            if message.role != "system"
        )
        self.state.add_user_message(messages, user_input)
        return messages

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


__all__ = ["HarnessCancelled", "HarnessRun"]
