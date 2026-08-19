"""Session lifecycle, persistence, and terminal outcomes for one harness run."""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from core_ai.registry import ModelRegistry
from core_ai.types import Message

from core_harness.control_plane import ControlPlane, IdentifiedControlPlane
from core_harness.errors import HarnessCancelled, HarnessLimitExceeded
from core_harness.models.control_plane import ControlCommandType
from core_harness.models.harness import HarnessResult, RunLimits, UsageTotals
from core_harness.models.tools import ToolCall
from core_harness.persistence import Checkpoint, Persistence
from core_harness.state import HarnessState, normalize_tool_protocol
from core_harness.tools import Tool
from core_harness.turn import TurnRunner


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
        limits: RunLimits,
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
        self.limits = limits
        self.max_turns = limits.max_turns
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
        run_id = str(uuid.uuid4())
        started_at = time.monotonic()
        identified = IdentifiedControlPlane(
            self.control_plane,
            run_id=run_id,
            session_id=active_session,
        )
        self.control_plane = identified

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
            },
        )
        await self._persist_conversation(active_session, messages)

        usage = UsageTotals()
        all_tool_calls: List[ToolCall] = []
        context_limit = self.state.context_limit(self.model_id)
        context_left: Optional[int] = None
        turn = 0
        deadline = None
        if self.limits.max_runtime_seconds is not None:
            deadline = started_at + self.limits.max_runtime_seconds
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
            max_tool_calls=self.limits.max_tool_calls,
            deadline=deadline,
            max_runtime_seconds=self.limits.max_runtime_seconds,
        )

        try:
            for turn in range(self.max_turns):
                self._raise_if_limit("max_runtime_seconds", time.monotonic() - started_at)
                self._raise_if_limit("max_tokens", usage.total_tokens)
                remaining = None
                if deadline is not None:
                    remaining = max(deadline - time.monotonic(), 0.0)
                turn_runner.remaining_runtime = remaining
                turn_runner.deadline = deadline
                messages = await self._apply_inbound_commands(messages, turn=turn)
                result = await turn_runner.run(
                    messages,
                    turn=turn,
                    usage=usage,
                    context_left=context_left,
                )
                context_left = result.context_left
                all_tool_calls.extend(result.tool_calls)
                self._raise_if_limit("max_tool_calls", len(all_tool_calls))
                self._raise_if_limit("max_tokens", usage.total_tokens)

                if not result.tool_calls:
                    await self._persist_state(
                        session_id=active_session,
                        turn=turn,
                        messages=messages,
                        usage=usage,
                        context_limit=context_limit,
                        context_left=context_left,
                        status="completed",
                        metadata={"output_text": result.assistant_text, "run_id": run_id},
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
                    metadata={"run_id": run_id},
                )
            self._exceed(
                "max_turns",
                float(self.max_turns),
                float(self.max_turns),
                f"Harness exceeded max_turns={self.max_turns}",
            )
        except HarnessCancelled as exc:
            await self.control_plane.emit(
                "run_cancelled",
                {"turn": turn, "reason": str(exc)},
            )
            await self._persist_state(
                session_id=active_session,
                turn=turn,
                messages=messages,
                usage=usage,
                context_limit=context_limit,
                context_left=context_left,
                status="cancelled",
                metadata={"reason": str(exc), "run_id": run_id},
            )
            raise
        except HarnessLimitExceeded as exc:
            await self.control_plane.emit(
                "run_limit_exceeded",
                {
                    "turn": turn,
                    "limit": exc.limit,
                    "value": exc.value,
                    "max": exc.maximum,
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
                metadata={
                    "limit": exc.limit,
                    "message": str(exc),
                    "run_id": run_id,
                },
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
                metadata={"error_type": type(exc).__name__, "message": str(exc), "run_id": run_id},
            )
            raise

    def _raise_if_limit(self, name: str, value: float) -> None:
        maximum = getattr(self.limits, name)
        if maximum is None:
            return
        if value > maximum or (name == "max_runtime_seconds" and value >= maximum):
            self._exceed(name, value, float(maximum), f"Harness exceeded {name}={maximum}")

    def _exceed(self, limit: str, value: float, maximum: float, message: str) -> None:
        raise HarnessLimitExceeded(limit, value, maximum, message)

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
        if getattr(self.control_plane, "cancelled", False):
            raise HarnessCancelled(getattr(self.control_plane, "cancel_reason", "cancelled"))

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
                raise HarnessCancelled(str(command.payload.get("reason", "cancelled")))
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


__all__ = ["HarnessCancelled", "HarnessLimitExceeded", "HarnessRun"]
