"""Subagent add-on: ChildConfig, child harness construction, and spawn_agent."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Iterable, List, Optional, Sequence, TYPE_CHECKING

from core_ai.types import Content
from core_harness.addons.addon import Addon
from core_harness.events import ControlPlane, IdentifiedControlPlane
from core_harness.models import HarnessResult
from core_harness.tools import Tool, current_tool_call_id

if TYPE_CHECKING:
    from core_harness.harness import CoreHarness


@dataclass
class ChildConfig:
    """Per-child overrides for a spawn. Omitted fields inherit from the parent."""

    model_id: Optional[str] = None
    max_turns: Optional[int] = None
    control_plane: Optional[ControlPlane] = None
    addons: Optional[Sequence[Addon]] = None
    addon_factory: Optional[Callable[[CoreHarness], Sequence[Addon]]] = None


@dataclass
class ChildIdentity:
    """Minted child identity. Does not include a constructed harness."""

    agent_id: str
    parent_id: Optional[str]
    spawn_depth: int
    label: str
    prompt_text: str
    control_plane: ControlPlane
    parent_plane: IdentifiedControlPlane
    blocked: bool = False
    blocked_message: str = ""
    tool_call_id: str = ""


class SubagentAddon(Addon):
    """Register ``spawn_agent`` and build child harnesses.

    Identity, depth, and lifecycle events stay on the parent harness.
    ``fork_for_child`` returns ``None`` so children do not get a nested spawn
    tool unless ``ChildConfig`` passes add-ons or a factory.
    """

    name = "subagent"

    def __init__(
        self,
        *,
        exclude_tools: Sequence[str] = ("spawn_agent",),
        max_turns: Optional[int] = None,
        configure: Optional[Callable[..., Optional[ChildConfig]]] = None,
        background: bool = False,
    ) -> None:
        self.exclude_tools = exclude_tools
        self.max_turns = max_turns
        self.configure = configure
        self.background = background

    def attach(self, harness: Any) -> None:
        harness.register_tool(self.make_spawn_tool(harness))

    def fork_for_child(self, parent_harness: Any) -> None:
        del parent_harness
        return None

    def child_addons(self, parent: CoreHarness, child_config: ChildConfig) -> List[Addon]:
        """Resolve child add-ons. Forks are the only inherit path from the parent."""
        del self
        if child_config.addons is not None:
            return list(child_config.addons)
        if child_config.addon_factory is not None:
            return list(child_config.addon_factory(parent))
        forked: List[Addon] = []
        for addon in parent.addons:
            child_addon = addon.fork_for_child(parent)
            if child_addon is not None:
                forked.append(child_addon)
        return forked

    def child_tools(
        self,
        parent: CoreHarness,
        *,
        tools: Optional[List[Tool]],
        exclude_tools: Iterable[str],
    ) -> List[Tool]:
        del self
        if tools is not None:
            return list(tools)
        blocked = set(exclude_tools)
        return [tool for name, tool in parent.tools.items() if name not in blocked]

    def build_child(
        self,
        parent: CoreHarness,
        identity: ChildIdentity,
        *,
        child_config: ChildConfig,
        tools: Optional[List[Tool]] = None,
        exclude_tools: Iterable[str] = ("spawn_agent",),
        system_prompt: Optional[str] = None,
        model_id: Optional[str] = None,
        max_turns: Optional[int] = None,
    ) -> CoreHarness:
        """Construct the child ``CoreHarness``. Does not run it."""
        from core_harness.harness import CoreHarness

        child_turns = max_turns if max_turns is not None else min(
            parent.max_turns, parent.config.spawn_max_turns
        )
        child_turns = max(1, min(child_turns, parent.config.spawn_max_turns))
        return CoreHarness(
            registry=parent.registry,
            model_id=model_id or parent.model_id,
            system_prompt=system_prompt or parent.config.subagent_system_prompt,
            config=parent.config.model_copy(update={"max_turns": child_turns}),
            reasoning_effort=parent.reasoning_effort,
            tools=self.child_tools(
                parent, tools=tools, exclude_tools=exclude_tools
            ),
            control_plane=identity.control_plane,
            session_id=identity.agent_id,
            addons=self.child_addons(parent, child_config),
            agent_id=identity.agent_id,
            parent_id=identity.parent_id,
            spawn_depth=identity.spawn_depth,
        )

    async def run_spawn(
        self,
        parent: CoreHarness,
        prompt: Content,
        *,
        label: str = "",
        tools: Optional[List[Tool]] = None,
        exclude_tools: Iterable[str] = ("spawn_agent",),
        system_prompt: Optional[str] = None,
        model_id: Optional[str] = None,
        max_turns: Optional[int] = None,
        child_config: Optional[ChildConfig] = None,
        background: bool = False,
    ) -> HarnessResult:
        """Build and run a child. Parent harness owns identity and lifecycle events."""
        cfg = child_config or ChildConfig()
        if background and sum(
            record.status == "running" for record in parent.child_tasks.values()
        ) >= parent.config.max_parallel_tool_calls:
            return HarnessResult(output_text="error: child concurrency limit reached; wait for an active child", messages=[])
        model_id = model_id or cfg.model_id
        max_turns = max_turns if max_turns is not None else cfg.max_turns
        identity = await parent.begin_child(
            label=label,
            prompt=prompt,
            control_plane=cfg.control_plane,
        )
        identity.tool_call_id = current_tool_call_id.get()
        if identity.blocked:
            return HarnessResult(
                output_text=identity.blocked_message,
                messages=[],
                tool_calls=[],
            )
        child = self.build_child(
            parent,
            identity,
            child_config=cfg,
            tools=tools,
            exclude_tools=exclude_tools,
            system_prompt=system_prompt,
            model_id=model_id,
            max_turns=max_turns,
        )
        if background:
            from core_harness.addons.subagent.background import start_child

            record = await start_child(parent, child, prompt, identity)
            return HarnessResult(output_text=json.dumps(record.snapshot()), messages=[])
        return await parent.run_child(child, prompt, identity=identity)

    def make_spawn_tool(self, harness: Any) -> Tool:
        """Model-facing wrapper around child construction and ``run_child``.

        ``configure`` is a product hook. It receives the model arguments and
        may return a :class:`ChildConfig` (for example a child-specific
        control plane). The add-on does not interpret approval policy or
        stamp parent/child identity.
        """
        default_max_turns = self.max_turns
        exclude_tools = self.exclude_tools
        configure = self.configure
        default_background = self.background

        async def spawn_agent(
            prompt: str,
            label: str = "",
            model_id: str = "",
            max_turns: int = 0,
            background: bool = default_background,
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
                        addons=(
                            override.addons
                            if override.addons is not None
                            else child_config.addons
                        ),
                        addon_factory=(
                            override.addon_factory
                            if override.addon_factory is not None
                            else child_config.addon_factory
                        ),
                    )
            if child_config.max_turns is None:
                child_config.max_turns = default_max_turns
            result = await self.run_spawn(
                harness,
                prompt,
                label=label,
                exclude_tools=exclude_tools,
                child_config=child_config,
                background=background,
            )
            if background or result.output_text.startswith("error:"):
                return result.output_text
            name = label.strip() or "child"
            return f"Subagent {name} completed.\n\n{result.output_text}"

        return Tool(
            spawn_agent,
            name="spawn_agent",
            description=(
                "Spawn a child agent for a focused subtask. Background work returns "
                "a child_id immediately. Continue independent work; the runtime "
                "delivers child results automatically between turns and waits for "
                "remaining children before finalizing your answer. No polling is needed. "
                f"Background defaults to {default_background}. "
                "Optionally set model_id and max_turns for that child. "
                "Children run without approval prompts and cannot spawn further "
                "agents."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "background": {
                        "type": "boolean",
                        "description": "Return immediately with a child ID. False waits for completion.",
                    },
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

__all__ = ["ChildConfig", "ChildIdentity", "SubagentAddon"]
