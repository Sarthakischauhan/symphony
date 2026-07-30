"""Coding agent built on core_harness."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Union

from core_ai.registry import ModelRegistry
from core_harness import ControlPlane, CoreHarness, HarnessResult, NullControlPlane, Tool

from coding_agent.prompts import SYSTEM_PROMPT
from coding_agent.tools import build_tools


class CodingAgent:
    """Product wrapper: workspace tools + CoreHarness loop."""

    def __init__(
        self,
        *,
        registry: ModelRegistry,
        model_id: str,
        workspace: Union[str, Path],
        control_plane: Optional[ControlPlane] = None,
        system_prompt: str = SYSTEM_PROMPT,
        max_turns: int = 124,
        tools: Optional[List[Tool]] = None,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.control_plane = control_plane or NullControlPlane()
        self.tools = tools if tools is not None else build_tools(self.workspace)
        self.harness = CoreHarness(
            registry=registry,
            model_id=model_id,
            system_prompt=system_prompt,
            tools=self.tools,
            control_plane=self.control_plane,
            max_turns=max_turns,
        )

    async def run(self, user_input: str) -> HarnessResult:
        return await self.harness.run(user_input)
