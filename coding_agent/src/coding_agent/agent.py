"""Coding agent built on core_harness."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Union

from core_ai.registry import ModelRegistry
from core_ai.types import Message
from core_harness import ControlPlane, CoreHarness, HarnessResult, NullControlPlane, Tool

from coding_agent.ast import build_ast_context
from coding_agent.prompts import SYSTEM_PROMPT
from coding_agent.tools import build_tools


class CodingAgent:
    """Product wrapper: workspace tools + CoreHarness loop.

    Conversation model:
    - Within one ``run()``, ``CoreHarness`` owns the full message list
      (system + user + assistant/tool turns).
    - Across ``run()`` calls this agent does **not** auto-accumulate history.
      Pass prior turns via ``conversation`` (no system message; harness prepends it).
    """

    def __init__(
        self,
        *,
        registry: ModelRegistry,
        model_id: str,
        workspace: Union[str, Path],
        control_plane: Optional[ControlPlane] = None,
        system_prompt: str = SYSTEM_PROMPT,
        ast_context_path: Optional[Union[str, Path]] = None,
        include_ast_context: bool = True,
        max_turns: int = 124,
        tools: Optional[List[Tool]] = None,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.control_plane = control_plane or NullControlPlane()
        self.tools = tools if tools is not None else build_tools(self.workspace)
        self.system_prompt = self._build_system_prompt(
            system_prompt,
            ast_context_path=ast_context_path,
            include_ast_context=include_ast_context,
        )
        self.harness = CoreHarness(
            registry=registry,
            model_id=model_id,
            system_prompt=self.system_prompt,
            tools=self.tools,
            control_plane=self.control_plane,
            max_turns=max_turns,
        )

    async def run(
        self,
        user_input: str,
        *,
        conversation: Optional[List[Message]] = None,
    ) -> HarnessResult:
        """Run one agent turn loop.

        ``conversation`` is optional prior history excluding the system prompt.
        Returns ``HarnessResult.messages`` including system + this run's turns;
        callers that want multi-run memory should persist and pass those back
        (typically ``result.messages[1:]``) on the next call.
        """
        return await self.harness.run(user_input, conversation=conversation)

    def _build_system_prompt(
        self,
        system_prompt: str,
        *,
        ast_context_path: Optional[Union[str, Path]],
        include_ast_context: bool,
    ) -> str:
        if not include_ast_context:
            return system_prompt

        context_root = (
            Path(ast_context_path).resolve()
            if ast_context_path
            else Path(__file__).parent
        )
        if not context_root.exists():
            return system_prompt

        context = build_ast_context(context_root)
        return f"{system_prompt.rstrip()}\n\n{context}\n"
