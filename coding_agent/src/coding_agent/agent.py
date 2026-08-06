"""Coding agent built on core_harness."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import List, Optional, Union

from core_ai.registry import ModelRegistry
from core_ai.types import Message
from core_harness import (
    ControlPlane,
    CoreHarness,
    HarnessCancelled,
    HarnessResult,
    NullControlPlane,
    Persistence,
    Tool,
)

from coding_agent.context import RepositoryContextProvider
from coding_agent.learning import LearningLoop, LearningStore
from coding_agent.persistence import SqlitePersistence
from coding_agent.prompts import SYSTEM_PROMPT
from coding_agent.tools import build_tools

logger = logging.getLogger(__name__)


class CodingAgent:
    """Product wrapper: workspace tools + CoreHarness loop.

    Conversation model:
    - Within one ``run()``, ``CoreHarness`` owns the full message list
      (system + user + assistant/tool turns).
    - Across ``run()`` calls, pass ``conversation`` and/or rely on ``persistence``
      + ``session_id`` so the harness can reload prior messages.
    - Per-run dynamic context (repo map + verified lessons) is injected via a
      harness hook and is not permanently grown into persisted history.
    - After each ``run()``, unverified task telemetry is journaled under
      ``.symphony/learning/``; only explicitly verified lessons enter the playbook.
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
        context_provider: Optional[RepositoryContextProvider] = None,
        max_repo_map_chars: int = 2500,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.control_plane = control_plane or NullControlPlane()
        self.session_id = session_id or str(uuid.uuid4())
        self.persistence = persistence or SqlitePersistence(
            self.workspace / ".symphony" / "sessions.sqlite3"
        )
        self.enable_learning = enable_learning
        self.include_ast_context = include_ast_context
        self.base_system_prompt = system_prompt
        self.learning_store = LearningStore(self.workspace)
        self.learning_loop = LearningLoop(self.learning_store) if enable_learning else None

        context_root = (
            Path(ast_context_path).resolve() if ast_context_path else self.workspace
        )
        self.context_provider = context_provider or RepositoryContextProvider(
            context_root,
            max_map_chars=max_repo_map_chars,
        )
        self.tools = (
            tools
            if tools is not None
            else build_tools(self.workspace, context_provider=self.context_provider)
        )
        # Static prompt only — dynamic context is attached per run.
        self.system_prompt = system_prompt.rstrip() + "\n"
        self.harness = CoreHarness(
            registry=registry,
            model_id=model_id,
            system_prompt=self.system_prompt,
            tools=self.tools,
            control_plane=self.control_plane,
            persistence=self.persistence,
            session_id=self.session_id,
            max_turns=max_turns,
            dynamic_context=self._dynamic_context,
        )

    def _dynamic_context(self) -> str:
        parts: list[str] = []
        if self.enable_learning:
            try:
                playbook = self.learning_store.playbook_context()
            except Exception:
                playbook = ""
            if playbook:
                parts.append(playbook)
        if self.include_ast_context:
            try:
                repo_map = self.context_provider.repo_map()
            except Exception:
                repo_map = ""
            if repo_map.strip():
                parts.append(repo_map.strip())
        return "\n\n".join(parts)

    async def run(
        self,
        user_input: str,
        *,
        conversation: Optional[List[Message]] = None,
        session_id: Optional[str] = None,
    ) -> HarnessResult:
        """Run one agent turn loop, then journal unverified task telemetry."""
        status = "completed"
        result: Optional[HarnessResult] = None
        try:
            result = await self.harness.run(
                user_input,
                conversation=conversation,
                session_id=session_id or self.session_id,
            )
            return result
        except HarnessCancelled:
            status = "cancelled"
            raise
        except Exception:
            status = "failed"
            raise
        finally:
            self._safe_after_task(user_input, result, status=status)

    def promote_lesson(self, **kwargs):
        """Promote a verified lesson into the playbook (explicit evidence required)."""
        if self.learning_loop is None:
            raise RuntimeError("learning is disabled on this agent")
        kwargs.setdefault("workspace_revision", self.context_provider.workspace_revision())
        return self.learning_loop.promote(**kwargs)

    def _safe_after_task(
        self,
        user_input: str,
        result: Optional[HarnessResult],
        *,
        status: str,
    ) -> None:
        if self.learning_loop is None:
            return
        try:
            revision = ""
            try:
                revision = self.context_provider.workspace_revision()
            except Exception:
                revision = ""
            if result is None:
                # Synthesize a minimal result for journaling cancellations/failures.
                from core_harness.models.harness import UsageTotals

                result = HarnessResult(
                    output_text="",
                    messages=[
                        Message(role="system", content=self.system_prompt),
                        Message(role="user", content=user_input),
                    ],
                    usage=UsageTotals(),
                )
            self.learning_loop.after_task(
                user_input,
                result,
                status=status,
                workspace_revision=revision,
            )
        except Exception:
            logger.exception("learning persistence failed; ignoring to preserve agent run")
