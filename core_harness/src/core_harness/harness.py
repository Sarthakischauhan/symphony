"""Public harness configuration and the run loop that uses it."""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Iterable, List, Optional, Sequence

from core_ai.content import text_from_content
from core_ai.registry import ModelRegistry
from core_ai.types import Content, Message

from core_harness.control_plane import ControlPlane, IdentifiedControlPlane, NullControlPlane
from core_harness.errors import HarnessCancelled, HarnessLimitExceeded
from core_harness.models import (
    ControlCommandType,
    HarnessResult,
    RunLimits,
    ToolCall,
    UsageTotals,
)
from core_harness.persistence import Checkpoint, NullPersistence, Persistence
from core_harness.state import Compactor, HarnessState, normalize_tool_protocol
from core_harness.tools import Tool
from core_harness.turn import TurnRunner

DEFAULT_MAX_SPAWN_DEPTH = 1
DEFAULT_SPAWN_MAX_TURNS = 8
DEFAULT_MAX_CONCURRENT_SPAWNS = 3
SUBAGENT_SYSTEM_PROMPT = (
    "You are a subagent spawned to complete one focused task. "
    "Use tools as needed. Do not ask the user. "
    "Return a concise, complete answer for the parent agent."
)


class CoreHarness:
    """Configured harness: tools, limits, persistence, and one-run execution."""

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
        max_tool_calls: Optional[int] = None,
        max_runtime_seconds: Optional[float] = None,
        max_tokens: Optional[int] = None,
        limits: Optional[RunLimits] = None,
        context_limits: Optional[Dict[str, int]] = None,
        context_warn_threshold: Optional[int] = None,
        context_compact_threshold: Optional[int] = None,
        compactor: Optional[Compactor] = None,
        tool_result_max_chars: Optional[int] = 12_000,
        context_target_tokens: Optional[int] = None,
        agent_id: Optional[str] = None,
        parent_id: Optional[str] = None,
        spawn_depth: int = 0,
        max_spawn_depth: int = DEFAULT_MAX_SPAWN_DEPTH,
    ) -> None:
        self.registry = registry
        self.model_id = model_id
        self.system_prompt = system_prompt
        self.control_plane = control_plane or NullControlPlane()
        self.persistence = persistence or NullPersistence()
        self.session_id = session_id
        self.limits = limits or RunLimits(
            max_turns=max_turns,
            max_tool_calls=max_tool_calls,
            max_runtime_seconds=max_runtime_seconds,
            max_tokens=max_tokens,
        )
        self.max_turns = self.limits.max_turns
        if tool_result_max_chars is not None and tool_result_max_chars < 1:
            raise ValueError("tool_result_max_chars must be positive or None")
        self.tool_result_max_chars = tool_result_max_chars
        self.context_target_tokens = context_target_tokens
        self.agent_id = agent_id or str(uuid.uuid4())
        self.parent_id = parent_id
        self.spawn_depth = spawn_depth
        self.max_spawn_depth = max_spawn_depth
        self._active_run_id: Optional[str] = None
        self._active_session_id: Optional[str] = None
        self.state = HarnessState(
            context_limits=context_limits,
            context_warn_threshold=context_warn_threshold,
            context_compact_threshold=context_compact_threshold,
            compactor=compactor,
            context_target_tokens=self.context_target_tokens,
        )
        self.tools: Dict[str, Tool] = {}
        for tool in tools or []:
            self.register_tool(tool)

    def register_tool(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def tool_schemas(self) -> List[Dict[str, Any]]:
        return [tool.get_schema() for tool in self.tools.values()]

    def _set_active_identity(self, run_id: str, session_id: str) -> None:
        self._active_run_id = run_id
        self._active_session_id = session_id

    def _parent_plane(self) -> IdentifiedControlPlane:
        return IdentifiedControlPlane(
            self.control_plane,
            run_id=self._active_run_id or str(uuid.uuid4()),
            session_id=self._active_session_id or self.session_id or str(uuid.uuid4()),
            agent_id=self.agent_id,
            parent_id=self.parent_id,
        )

    def _child_tools(self, exclude_tools: Iterable[str]) -> List[Tool]:
        blocked = set(exclude_tools)
        return [tool for name, tool in self.tools.items() if name not in blocked]

    def make_spawn_tool(
        self,
        *,
        exclude_tools: Sequence[str] = ("spawn_agent",),
        max_turns: Optional[int] = None,
    ) -> Tool:
        """Model-facing wrapper around :meth:`spawn`."""

        async def spawn_agent(prompt: str, label: str = "") -> str:
            result = await self.spawn(
                prompt,
                label=label,
                exclude_tools=exclude_tools,
                max_turns=max_turns,
            )
            name = label.strip() or "child"
            return f"Subagent {name} completed.\n\n{result.output_text}"

        return Tool(
            spawn_agent,
            name="spawn_agent",
            description=(
                "Spawn a child agent for a focused subtask. Call this multiple "
                "times in one turn to run up to three independent children in "
                "parallel. Each child has its own conversation and tool loop; "
                "events stream on the same control plane tagged with parent_id "
                "and agent_id. Returns the child's final answer. Children cannot "
                "spawn further agents."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "The full task for the child agent to complete.",
                    },
                    "label": {
                        "type": "string",
                        "description": "Short name shown in the UI, e.g. 'inspect auth'.",
                    },
                },
                "required": ["prompt"],
                "additionalProperties": False,
            },
            parallel=True,
        )

    async def spawn(
        self,
        prompt: Content,
        *,
        label: str = "",
        tools: Optional[List[Tool]] = None,
        exclude_tools: Iterable[str] = ("spawn_agent",),
        system_prompt: Optional[str] = None,
        model_id: Optional[str] = None,
        max_turns: Optional[int] = None,
    ) -> HarnessResult:
        """Run a child harness that shares this control plane with parent/child ids."""
        prompt_text = text_from_content(prompt)
        child_id = str(uuid.uuid4())
        plane = self._parent_plane()
        if self.spawn_depth >= self.max_spawn_depth:
            message = (
                f"error: spawn depth {self.spawn_depth} exceeds "
                f"max_spawn_depth={self.max_spawn_depth}"
            )
            await plane.emit(
                "agent_failed",
                {
                    "child_id": child_id,
                    "label": label,
                    "prompt": prompt_text,
                    "message": message,
                },
            )
            return HarnessResult(output_text=message, messages=[], tool_calls=[])

        child_tools = tools if tools is not None else self._child_tools(exclude_tools)
        child_turns = max_turns if max_turns is not None else min(
            self.max_turns, DEFAULT_SPAWN_MAX_TURNS
        )
        child = CoreHarness(
            registry=self.registry,
            model_id=model_id or self.model_id,
            system_prompt=system_prompt or SUBAGENT_SYSTEM_PROMPT,
            tools=child_tools,
            control_plane=self.control_plane,
            persistence=NullPersistence(),
            session_id=str(uuid.uuid4()),
            max_turns=child_turns,
            max_tool_calls=self.limits.max_tool_calls,
            max_runtime_seconds=self.limits.max_runtime_seconds,
            max_tokens=self.limits.max_tokens,
            context_limits=self.state.context_limits,
            context_warn_threshold=self.state.context_warn_threshold,
            context_compact_threshold=self.state.context_compact_threshold,
            compactor=self.state.compactor,
            tool_result_max_chars=self.tool_result_max_chars,
            context_target_tokens=self.context_target_tokens,
            agent_id=child_id,
            parent_id=self.agent_id,
            spawn_depth=self.spawn_depth + 1,
            max_spawn_depth=self.max_spawn_depth,
        )
        await plane.emit(
            "agent_spawned",
            {
                "child_id": child_id,
                "label": label,
                "prompt": prompt_text,
                "model_id": child.model_id,
                "depth": child.spawn_depth,
            },
        )
        try:
            result = await child.run(prompt)
        except (HarnessCancelled, HarnessLimitExceeded) as exc:
            await plane.emit(
                "agent_failed",
                {
                    "child_id": child_id,
                    "label": label,
                    "message": str(exc),
                    "error_type": type(exc).__name__,
                },
            )
            return HarnessResult(
                output_text=f"error: subagent {type(exc).__name__}: {exc}",
                messages=[],
                tool_calls=[],
            )
        except Exception as exc:  # noqa: BLE001
            await plane.emit(
                "agent_failed",
                {
                    "child_id": child_id,
                    "label": label,
                    "message": str(exc),
                    "error_type": type(exc).__name__,
                },
            )
            return HarnessResult(
                output_text=f"error: subagent failed: {exc}",
                messages=[],
                tool_calls=[],
            )
        await plane.emit(
            "agent_completed",
            {
                "child_id": child_id,
                "label": label,
                "output_text": result.output_text,
                "usage": result.usage.model_dump(),
            },
        )
        return result

    async def run(
        self,
        user_input: Content,
        *,
        conversation: Optional[List[Message]] = None,
        session_id: Optional[str] = None,
    ) -> HarnessResult:
        """Run turns until the model stops calling tools or a limit is hit."""
        active_session = session_id or self.session_id or str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        started_at = time.monotonic()
        plane = IdentifiedControlPlane(
            self.control_plane,
            run_id=run_id,
            session_id=active_session,
            agent_id=self.agent_id,
            parent_id=self.parent_id,
        )

        messages = await self._initial_messages(
            active_session,
            user_input,
            conversation,
        )
        await plane.emit(
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
            tool_schemas=self.tool_schemas(),
            tools=self.tools,
            control_plane=plane,
            state=self.state,
            context_limit=context_limit,
            tool_result_max_chars=self.tool_result_max_chars,
            context_target_tokens=self.context_target_tokens,
            max_tool_calls=self.limits.max_tool_calls,
            deadline=deadline,
            max_runtime_seconds=self.limits.max_runtime_seconds,
            agent_id=self.agent_id,
            parent_id=self.parent_id,
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
                messages = await self._apply_inbound_commands(
                    messages, turn=turn, control_plane=plane
                )
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
                    await plane.emit(
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
            await plane.emit("run_cancelled", {"turn": turn, "reason": str(exc)})
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
            await plane.emit(
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
            await plane.emit(
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
        user_input: Content,
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
        control_plane: ControlPlane,
    ) -> List[Message]:
        if getattr(control_plane, "cancelled", False):
            raise HarnessCancelled(getattr(control_plane, "cancel_reason", "cancelled"))

        wait_if_paused = getattr(control_plane, "wait_if_paused", None)
        if wait_if_paused is not None and getattr(control_plane, "paused", False):
            await control_plane.emit("paused", {"turn": turn})
            await wait_if_paused()
            await control_plane.emit("resumed", {"turn": turn})

        drain = getattr(control_plane, "drain_commands", None)
        if drain is None:
            return messages

        for command in await drain():
            if command.type == ControlCommandType.CANCEL:
                raise HarnessCancelled(str(command.payload.get("reason", "cancelled")))
            if command.type == ControlCommandType.INJECT_MESSAGE:
                injected = command.to_message()
                messages.append(injected)
                await control_plane.emit(
                    "message_injected",
                    {
                        "turn": turn,
                        "role": injected.role,
                        "content": injected.content,
                    },
                )
        return messages


__all__ = [
    "CoreHarness",
    "DEFAULT_MAX_CONCURRENT_SPAWNS",
    "DEFAULT_MAX_SPAWN_DEPTH",
    "DEFAULT_SPAWN_MAX_TURNS",
    "HarnessCancelled",
    "HarnessLimitExceeded",
    "SUBAGENT_SYSTEM_PROMPT",
]
