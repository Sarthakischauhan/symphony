"""Subagent add-on: ChildConfig and spawn_agent tool registration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence

from core_harness.events import ControlPlane
from core_harness.tools import Tool


@dataclass
class ChildConfig:
    """Per-child overrides for a spawn. Omitted fields inherit from the parent."""

    model_id: Optional[str] = None
    max_turns: Optional[int] = None
    control_plane: Optional[ControlPlane] = None


class SubagentAddon:
    """Register the ``spawn_agent`` tool. Identity and depth stay on the harness."""

    name = "subagent"
    inherit_on_spawn = False

    def __init__(
        self,
        *,
        exclude_tools: Sequence[str] = ("spawn_agent",),
        max_turns: Optional[int] = None,
        configure: Optional[Callable[..., Optional[ChildConfig]]] = None,
    ) -> None:
        self.exclude_tools = exclude_tools
        self.max_turns = max_turns
        self.configure = configure

    def attach(self, harness: Any) -> None:
        harness.register_tool(self.make_spawn_tool(harness))

    def make_spawn_tool(self, harness: Any) -> Tool:
        """Model-facing wrapper around ``CoreHarness.spawn``.

        ``configure`` is a product hook. It receives the model arguments and
        may return a :class:`ChildConfig` (for example a child-specific
        control plane). The add-on does not interpret approval policy or
        stamp parent/child identity.
        """
        default_max_turns = self.max_turns
        exclude_tools = self.exclude_tools
        configure = self.configure

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
            result = await harness.spawn(
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


__all__ = ["ChildConfig", "SubagentAddon"]
