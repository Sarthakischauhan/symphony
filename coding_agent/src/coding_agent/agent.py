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
    KeepSystemRecentCompactor,
    NullControlPlane,
    Persistence,
    Tool,
)
from core_harness.utils.tokens import estimate_prompt_tokens

from coding_agent.learning import LearningLoop, LearningStore
from coding_agent.persistence import SqlitePersistence
from coding_agent.prompts import SYSTEM_PROMPT
from coding_agent.tools import build_tools


class CodingAgent:
    """Workspace tools, persisted conversation, and optional post-run learning."""

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
        enable_learning: bool = True,
        max_turns: int = 124,
        tools: Optional[List[Tool]] = None,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.control_plane = control_plane or NullControlPlane()
        self.registry = registry
        self.session_id = session_id or str(uuid.uuid4())
        self.persistence = persistence or SqlitePersistence(
            self.workspace / ".symphony" / "sessions.sqlite3"
        )
        self.base_system_prompt = system_prompt.rstrip()
        self.learning_store = LearningStore(self.workspace)
        self.learning_loop = (
            LearningLoop(self.learning_store, registry=registry, model_id=model_id)
            if enable_learning
            else None
        )
        self.tools = tools if tools is not None else build_tools(self.workspace)
        self.harness = CoreHarness(
            registry=registry,
            model_id=model_id,
            system_prompt=self.base_system_prompt + "\n",
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
        """Run the agent and schedule reflection only after successful completion."""
        lessons = self.learning_store.context_for(user_input) if self.learning_loop else ""
        self.harness.system_prompt = self.base_system_prompt
        if lessons:
            self.harness.system_prompt += f"\n\n{lessons}"
        self.harness.system_prompt += "\n"

        result = await self.harness.run(
            user_input,
            conversation=conversation,
            session_id=session_id or self.session_id,
        )
        if self.learning_loop is not None:
            self.learning_loop.schedule(user_input, result)
        return result

    async def wait_for_learning(self) -> None:
        """Optionally drain pending reflections before application shutdown."""
        if self.learning_loop is not None:
            await self.learning_loop.wait()

    async def compact_conversation(self, *, keep_recent: int = 8) -> tuple[int, int]:
        """Manually compact the persisted conversation for the active session."""
        messages = await self.persistence.load_conversation(session_id=self.session_id)
        before = len(messages)
        if not messages:
            return (0, 0)

        before_tokens = estimate_prompt_tokens(messages)
        await self.control_plane.emit(
            "compaction_started",
            {
                "turn": 0,
                "message_count": before,
                "tokens_used": before_tokens,
                "context_left": None,
                "manual": True,
            },
        )
        compacted = await KeepSystemRecentCompactor(keep_recent=keep_recent).compact(
            messages,
            turn=0,
            context_limit=self.harness.state.context_limit(self.harness.model_id),
            tokens_used=before_tokens,
            context_left=None,
        )
        await self.persistence.save_conversation(
            session_id=self.session_id,
            messages=compacted,
        )
        await self.control_plane.emit(
            "compaction_completed",
            {
                "turn": 0,
                "message_count_before": before,
                "message_count_after": len(compacted),
                "estimated_tokens_before": before_tokens,
                "estimated_tokens_after": estimate_prompt_tokens(compacted),
                "manual": True,
            },
        )
        return (before, len(compacted))
