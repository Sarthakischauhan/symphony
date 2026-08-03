"""Coding agent built on core_harness."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import List, Optional, Union

from core_ai.registry import ModelRegistry
from core_ai.types import Message
from core_harness import (
    ControlPlane,
    CoreHarness,
    HarnessResult,
    NullControlPlane,
    Persistence,
    Tool,
)

from coding_agent.ast import build_ast_context
from coding_agent.learning import LearningLoop, LearningStore
from coding_agent.persistence import SqlitePersistence
from coding_agent.prompts import SYSTEM_PROMPT
from coding_agent.tools import build_tools


class CodingAgent:
    """Product wrapper: workspace tools + CoreHarness loop.

    Conversation model:
    - Within one ``run()``, ``CoreHarness`` owns the full message list
      (system + user + assistant/tool turns).
    - Across ``run()`` calls, pass ``conversation`` and/or rely on ``persistence``
      + ``session_id`` so the harness can reload prior messages.
    - After each ``run()``, an optional self-learning loop records what worked /
      failed under ``<workspace>/.symphony/learning/``.
    """

    def __init__(
        self,
        *,
        registry: ModelRegistry,
        model_id: str,
        workspace: Union[str, Path],
        control_plane: Optional[ControlPlane] = None,
        persistence: Optional[Persistence] = None,
        session_id: Optional[str] = None,
        system_prompt: str = SYSTEM_PROMPT,
        ast_context_path: Optional[Union[str, Path]] = None,
        include_ast_context: bool = True,
        enable_learning: bool = True,
        max_turns: int = 124,
        tools: Optional[List[Tool]] = None,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.control_plane = control_plane or NullControlPlane()
        self.session_id = session_id or str(uuid.uuid4())
        self.persistence = persistence or SqlitePersistence(
            self.workspace / ".symphony" / "sessions.sqlite3"
        )
        self.enable_learning = enable_learning
        self.learning_store = LearningStore(self.workspace)
        self.learning_loop = LearningLoop(self.learning_store) if enable_learning else None
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
            persistence=self.persistence,
            session_id=self.session_id,
            max_turns=max_turns,
        )

    async def run(
        self,
        user_input: str,
        *,
        conversation: Optional[List[Message]] = None,
        session_id: Optional[str] = None,
    ) -> HarnessResult:
        """Run one agent turn loop, then record self-learning lessons."""
        result = await self.harness.run(
            user_input,
            conversation=conversation,
            session_id=session_id or self.session_id,
        )
        if self.learning_loop is not None:
            self.learning_loop.after_task(user_input, result)
        return result

    def _build_system_prompt(
        self,
        system_prompt: str,
        *,
        ast_context_path: Optional[Union[str, Path]],
        include_ast_context: bool,
    ) -> str:
        parts = [system_prompt.rstrip()]

        if self.enable_learning:
            playbook = self.learning_store.playbook_context()
            if playbook:
                parts.append(playbook)

        if include_ast_context:
            context_root = (
                Path(ast_context_path).resolve()
                if ast_context_path
                else Path.cwd()
            )
            if context_root.exists():
                context = build_ast_context(context_root)
                if context.strip():
                    parts.append(context.strip())

        return "\n\n".join(parts) + "\n"
