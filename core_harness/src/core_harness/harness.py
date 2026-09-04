"""Public harness configuration and the run loop that uses it."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Iterable, List, Optional, Sequence

from core_ai.content import text_from_content
from core_ai.registry import ModelRegistry
from core_ai.types import Content, Message

from core_harness.addons import Addon
from core_harness.addons.persistence import Checkpoint, NullPersistence
from core_harness.addons.subagent import ChildConfig, ChildIdentity
from core_harness.addons.telemetry import NullTelemetry
from core_harness.config import SettingsSource, resolve_harness_config
from core_harness.events import ControlPlane, IdentifiedControlPlane, NullControlPlane
from core_harness.errors import HarnessCancelled, HarnessLimitExceeded
from core_harness.models import (
    HarnessResult,
    RunLimits,
    UsageTotals,
)
from core_harness.context import HarnessState, normalize_tool_protocol
from core_harness.tools import Tool


class CoreHarness:
    """Configured harness: tools, limits, run loop, and attached add-ons."""

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
        session_id: Optional[str] = None,
        addons: Optional[Sequence[Addon]] = None,
        agent_id: Optional[str] = None,
        parent_id: Optional[str] = None,
        spawn_depth: int = 0,
    ) -> None:
        self.config = resolve_harness_config(config)
        self.registry = registry
        self.model_id = model_id
        self.reasoning_effort = reasoning_effort
        self.system_prompt = system_prompt
        self.control_plane = control_plane or NullControlPlane()
        self.persistence = NullPersistence()
        self.telemetry = NullTelemetry()
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
            context_target_tokens=self.context_target_tokens,
        )
        self.addons: List[Addon] = []
        self.tools: Dict[str, Tool] = {}
        for tool in tools or []:
            self.register_tool(tool)
        for addon in addons or []:
            self.register_addon(addon)

    def register_addon(self, addon: Addon) -> None:
        """Attach an add-on. Skills can use this path later; there is no loader."""
        if any(existing.name == addon.name for existing in self.addons):
            raise ValueError(f"duplicate addon name: {addon.name!r}")
        addon.attach(self)
        self.addons.append(addon)

    async def notify_addons(self, hook: str, **payload: Any) -> None:
        for addon in self.addons:
            if hook == "before_turn":
                await addon.before_turn(**payload)
            elif hook == "after_turn":
                await addon.after_turn(**payload)
            elif hook == "after_run":
                await addon.after_run(**payload)
            elif hook == "on_tool":
                await addon.on_tool(**payload)
            elif hook == "on_compact":
                await addon.on_compact(**payload)
            else:
                raise ValueError(f"unknown addon hook: {hook!r}")

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

    def _subagent_addon(self):
        from core_harness.addons.subagent import SubagentAddon

        for addon in self.addons:
            if isinstance(addon, SubagentAddon):
                return addon
        return SubagentAddon()

    async def begin_child(
        self,
        *,
        label: str = "",
        prompt: Content = "",
        control_plane: Optional[ControlPlane] = None,
    ) -> ChildIdentity:
        """Mint child identity and check depth. Does not construct a harness."""
        prompt_text = text_from_content(prompt)
        child_id = str(uuid.uuid4())
        parent_plane = self._parent_plane()
        child_plane = control_plane or self.control_plane
        if self.spawn_depth >= self.max_spawn_depth:
            message = (
                f"error: spawn depth {self.spawn_depth} exceeds "
                f"max_spawn_depth={self.max_spawn_depth}"
            )
            await parent_plane.emit(
                "agent_failed",
                {
                    "child_id": child_id,
                    "label": label,
                    "prompt": prompt_text,
                    "message": message,
                },
            )
            return ChildIdentity(
                agent_id=child_id,
                parent_id=self.agent_id,
                spawn_depth=self.spawn_depth + 1,
                label=label,
                prompt_text=prompt_text,
                control_plane=child_plane,
                parent_plane=parent_plane,
                blocked=True,
                blocked_message=message,
            )
        return ChildIdentity(
            agent_id=child_id,
            parent_id=self.agent_id,
            spawn_depth=self.spawn_depth + 1,
            label=label,
            prompt_text=prompt_text,
            control_plane=child_plane,
            parent_plane=parent_plane,
        )

    async def run_child(
        self,
        child: CoreHarness,
        prompt: Content,
        *,
        identity: ChildIdentity,
    ) -> HarnessResult:
        """Emit lifecycle events and await ``child.run``."""
        plane = identity.parent_plane
        await plane.emit(
            "agent_spawned",
            {
                "child_id": child.agent_id,
                "label": identity.label,
                "prompt": identity.prompt_text,
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
                    "child_id": child.agent_id,
                    "label": identity.label,
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
                    "child_id": child.agent_id,
                    "label": identity.label,
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
                "child_id": child.agent_id,
                "label": identity.label,
                "output_text": result.output_text,
                "usage": result.usage.model_dump(),
            },
        )
        return result

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
        """Run a child harness. Identity, depth, and lifecycle events stay here."""
        return await self._subagent_addon().run_spawn(
            self,
            prompt,
            label=label,
            tools=tools,
            exclude_tools=exclude_tools,
            system_prompt=system_prompt,
            model_id=model_id,
            max_turns=max_turns,
            child_config=child_config,
        )

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
    "CoreHarness",
    "HarnessCancelled",
    "HarnessLimitExceeded",
]
