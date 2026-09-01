"""Public harness configuration and the run loop that uses it."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from core_ai.content import text_from_content
from core_ai.registry import ModelRegistry
from core_ai.types import Content, Message

from core_harness.config import SettingsSource, resolve_harness_config
from core_harness.events import ControlPlane, IdentifiedControlPlane, NullControlPlane
from core_harness.errors import HarnessCancelled, HarnessLimitExceeded
from core_harness.models import (
    HarnessResult,
    RunLimits,
    UsageTotals,
)
from core_harness.persistence import Checkpoint, NullPersistence, Persistence
from core_harness.context import (
    Compactor,
    HarnessState,
    KeepSystemRecentCompactor,
    normalize_tool_protocol,
)
from core_harness.tools import Tool


@dataclass
class ChildConfig:
    """Per-child overrides for a spawn. Omitted fields inherit from the parent."""

    model_id: Optional[str] = None
    max_turns: Optional[int] = None
    control_plane: Optional[ControlPlane] = None


class CoreHarness:
    """Configured harness: tools, limits, persistence, and one-run execution."""

    def __init__(
        self,
        *,
        registry: ModelRegistry,
        model_id: str,
        system_prompt: str,
        config: SettingsSource,
        reasoning_effort: Optional[str] = None,
        tools: Optional[List[Tool]] = None,
        control_plane: Optional[ControlPlane] = None,
        persistence: Optional[Persistence] = None,
        session_id: Optional[str] = None,
        compactor: Optional[Compactor] = None,
        agent_id: Optional[str] = None,
        parent_id: Optional[str] = None,
        spawn_depth: int = 0,
    ) -> None:
        self.config = resolve_harness_config(config)
        if compactor is None and self.config.context_compact_threshold is not None:
            compactor = KeepSystemRecentCompactor(
                keep_recent=self.config.compaction_keep_recent,
                target_tokens=self.config.context_target_tokens,
                keep_recent_tool_results=self.config.tool_result_keep_recent,
            )
        self.registry = registry
        self.model_id = model_id
        self.reasoning_effort = reasoning_effort
        self.system_prompt = system_prompt
        self.control_plane = control_plane or NullControlPlane()
        self.persistence = persistence or NullPersistence()
        self.session_id = session_id
        self.limits = RunLimits(
            max_turns=self.config.max_turns,
            max_tool_calls=self.config.max_tool_calls,
            max_runtime_seconds=self.config.max_runtime_seconds,
            max_tokens=self.config.max_tokens,
        )
        self.max_turns = self.limits.max_turns
        self.tool_result_max_chars = self.config.tool_result_max_chars
        self.tool_result_keep_recent = self.config.tool_result_keep_recent
        self.tool_result_prune_tokens = self.config.tool_result_prune_tokens
        self.context_target_tokens = self.config.context_target_tokens
        self.agent_id = agent_id or str(uuid.uuid4())
        self.parent_id = parent_id
        self.spawn_depth = spawn_depth
        self.max_spawn_depth = self.config.max_spawn_depth
        self._active_run_id: Optional[str] = None
        self._active_session_id: Optional[str] = None
        self.state = HarnessState(
            context_limits=self.config.context_limits,
            context_warn_threshold=self.config.context_warn_threshold,
            context_compact_threshold=self.config.context_compact_threshold,
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
        configure: Optional[Callable[..., Optional[ChildConfig]]] = None,
    ) -> Tool:
        """Model-facing wrapper around :meth:`spawn`.

        ``configure`` is a product hook. It receives the model arguments and
        may return a :class:`ChildConfig` (for example a child-specific
        control plane). The harness itself does not interpret approval policy.
        """
        default_max_turns = max_turns

        async def spawn_agent(
            prompt: str,
            label: str = "",
            model_id: str = "",
            max_turns: int = 0,
        ) -> str:
            child_config = ChildConfig(
                model_id=model_id or None,
                max_turns=max_turns or None,
            )
            if configure is not None:
                override = configure(
                    prompt=prompt,
                    label=label,
                    model_id=model_id or None,
                    max_turns=max_turns or None,
                )
                if override is not None:
                    child_config = ChildConfig(
                        model_id=override.model_id or child_config.model_id,
                        max_turns=(
                            override.max_turns
                            if override.max_turns is not None
                            else child_config.max_turns
                        ),
                        control_plane=override.control_plane or child_config.control_plane,
                    )
            if child_config.max_turns is None:
                child_config.max_turns = default_max_turns
            result = await self.spawn(
                prompt,
                label=label,
                exclude_tools=exclude_tools,
                child_config=child_config,
            )
            name = label.strip() or "child"
            return f"Subagent {name} completed.\n\n{result.output_text}"

        return Tool(
            spawn_agent,
            name="spawn_agent",
            description=(
                "Spawn a child agent for a focused subtask. Call this multiple "
                "times in one turn to run up to three independent children in "
                "parallel. Optionally set model_id and max_turns for that child. "
                "Children run without approval prompts and cannot spawn further "
                "agents."
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
                    "model_id": {
                        "type": "string",
                        "description": "Optional model for the child. Defaults to the parent model.",
                    },
                    "max_turns": {
                        "type": "integer",
                        "description": "Optional turn cap for the child, limited by spawn_max_turns.",
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
        child_config: Optional[ChildConfig] = None,
    ) -> HarnessResult:
        """Run a child harness. Lifecycle events stay on the parent plane."""
        cfg = child_config or ChildConfig()
        model_id = model_id or cfg.model_id
        max_turns = max_turns if max_turns is not None else cfg.max_turns
        child_plane = cfg.control_plane or self.control_plane
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
            self.max_turns, self.config.spawn_max_turns
        )
        child_turns = max(1, min(child_turns, self.config.spawn_max_turns))
        child = CoreHarness(
            registry=self.registry,
            model_id=model_id or self.model_id,
            system_prompt=system_prompt or self.config.subagent_system_prompt,
            config=self.config.model_copy(update={"max_turns": child_turns}),
            reasoning_effort=self.reasoning_effort,
            tools=child_tools,
            control_plane=child_plane,
            persistence=NullPersistence(),
            session_id=str(uuid.uuid4()),
            compactor=self.state.compactor,
            agent_id=child_id,
            parent_id=self.agent_id,
            spawn_depth=self.spawn_depth + 1,
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
        from core_harness.loop import run_session

        return await run_session(
            self,
            user_input,
            conversation=conversation,
            session_id=session_id,
        )

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


__all__ = [
    "ChildConfig",
    "CoreHarness",
    "HarnessCancelled",
    "HarnessLimitExceeded",
]
