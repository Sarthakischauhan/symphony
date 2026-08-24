"""Coding agent built on core_harness."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Dict, List, Literal, Optional, Union

from core_ai.content import text_from_content
from core_ai.registry import ModelRegistry
from core_ai.types import Content, Message
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
from coding_agent.plan import PlanStore
from coding_agent.prompts import PLAN_MODE_PROMPT, SYSTEM_PROMPT
from coding_agent.tools import build_tools, wrap_with_approvals

AgentMode = Literal["build", "plan"]

DEFAULT_CONTEXT_WARN_THRESHOLD = 32_000
DEFAULT_CONTEXT_COMPACT_THRESHOLD = 16_000
DEFAULT_COMPACTION_KEEP_RECENT = 8
DEFAULT_CONTEXT_TARGET_TOKENS = 80_000
DEFAULT_MAX_TURNS = 24
DEFAULT_MAX_TOOL_CALLS = 40
DEFAULT_MAX_RUNTIME_SECONDS = 600.0
DEFAULT_MAX_TOKENS: None = None


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
        mode: AgentMode = "build",
        enable_learning: bool = True,
        auto_approve: bool = False,
        max_turns: int = DEFAULT_MAX_TURNS,
        max_tool_calls: Optional[int] = DEFAULT_MAX_TOOL_CALLS,
        max_runtime_seconds: Optional[float] = DEFAULT_MAX_RUNTIME_SECONDS,
        max_tokens: Optional[int] = DEFAULT_MAX_TOKENS,
        tools: Optional[List[Tool]] = None,
        context_limits: Optional[Dict[str, int]] = None,
        context_warn_threshold: Optional[int] = DEFAULT_CONTEXT_WARN_THRESHOLD,
        context_compact_threshold: Optional[int] = DEFAULT_CONTEXT_COMPACT_THRESHOLD,
        compaction_keep_recent: int = DEFAULT_COMPACTION_KEEP_RECENT,
        tool_result_max_chars: Optional[int] = 12_000,
        context_target_tokens: Optional[int] = DEFAULT_CONTEXT_TARGET_TOKENS,
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
        self.mode = mode
        self.plan_store = PlanStore(self.workspace)
        self.learning_store = LearningStore(self.workspace)
        self.learning_loop = (
            LearningLoop(self.learning_store, registry=registry, model_id=model_id)
            if enable_learning
            else None
        )
        raw_tools = tools if tools is not None else build_tools(self.workspace)
        self.tools = raw_tools if auto_approve else wrap_with_approvals(raw_tools, self.workspace)
        self.harness = CoreHarness(
            registry=registry,
            model_id=model_id,
            system_prompt=self.base_system_prompt + "\n",
            tools=self.tools,
            control_plane=self.control_plane,
            persistence=self.persistence,
            session_id=self.session_id,
            max_turns=max_turns,
            max_tool_calls=max_tool_calls,
            max_runtime_seconds=max_runtime_seconds,
            max_tokens=max_tokens,
            context_limits=context_limits,
            context_warn_threshold=context_warn_threshold,
            context_compact_threshold=context_compact_threshold,
            compactor=(
                KeepSystemRecentCompactor(keep_recent=compaction_keep_recent)
                if context_compact_threshold is not None
                else None
            ),
            tool_result_max_chars=tool_result_max_chars,
            context_target_tokens=context_target_tokens,
        )

    async def run(
        self,
        user_input: Content,
        *,
        conversation: Optional[List[Message]] = None,
        session_id: Optional[str] = None,
    ) -> HarnessResult:
        """Run the agent and schedule reflection only after successful completion."""
        mode = self.mode
        task_text = text_from_content(user_input)
        lessons = self.learning_store.context_for(task_text) if self.learning_loop else ""
        self.harness.system_prompt = self.base_system_prompt
        if lessons:
            self.harness.system_prompt += f"\n\n{lessons}"
        if mode == "plan":
            self.harness.system_prompt += f"\n\n{PLAN_MODE_PROMPT}"
        self.harness.system_prompt += "\n"

        tools = self.harness.tools
        if mode == "plan":
            self.plan_store.begin(task_text)
            self.harness.tools = {
                name: tool
                for name, tool in tools.items()
                if name in {"read_file", "search"}
            }
        try:
            result = await self.harness.run(
                user_input,
                conversation=conversation,
                session_id=session_id or self.session_id,
            )
        finally:
            self.harness.tools = tools

        if mode == "plan":
            self.plan_store.save(task_text, result.output_text)
        elif self.learning_loop is not None:
            self.learning_loop.schedule(task_text, result)
        return result

    def set_mode(self, mode: AgentMode) -> None:
        self.mode = mode

    async def wait_for_learning(self) -> None:
        """Optionally drain pending reflections before application shutdown."""
        if self.learning_loop is not None:
            await self.learning_loop.wait()

    async def shutdown_learning(self) -> None:
        """Cancel or finish pending reflection when the TUI exits."""
        if self.learning_loop is not None:
            await self.learning_loop.shutdown()

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
