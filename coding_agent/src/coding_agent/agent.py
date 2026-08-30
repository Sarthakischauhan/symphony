"""Coding agent built on core_harness."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

from core_ai.content import text_from_content
from core_ai.registry import ModelRegistry
from core_ai.types import Content, Message
from core_harness import (
    ChildConfig,
    ControlPlane,
    CoreHarness,
    HarnessResult,
    KeepSystemRecentCompactor,
    NullControlPlane,
    Persistence,
    Tool,
)
from core_harness.state import ContextReport, build_context_report
from core_harness.utils.tokens import estimate_prompt_tokens

from coding_agent.config import (
    DEFAULT_CODING_AGENT_CONFIG,
    CodingAgentConfig,
    load_coding_agent_config,
)
from coding_agent.learning import LearningLoop, LearningStore
from coding_agent.persistence import SqlitePersistence
from coding_agent.plan import PlanStore
from coding_agent.prompts import PLAN_MODE_PROMPT, SYSTEM_PROMPT
from coding_agent.tools import build_tools

AgentMode = Literal["build", "plan"]

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
        config: Optional[CodingAgentConfig] = None,
        system_prompt: str = SYSTEM_PROMPT,
        mode: AgentMode = "build",
        enable_learning: Optional[bool] = None,
        auto_approve: Optional[bool] = None,
        max_turns: int = DEFAULT_CODING_AGENT_CONFIG.harness.max_turns,
        max_tool_calls: Optional[int] = DEFAULT_CODING_AGENT_CONFIG.harness.max_tool_calls,
        max_runtime_seconds: Optional[float] = DEFAULT_CODING_AGENT_CONFIG.harness.max_runtime_seconds,
        max_tokens: Optional[int] = DEFAULT_CODING_AGENT_CONFIG.harness.max_tokens,
        tools: Optional[List[Tool]] = None,
        context_limits: Optional[Dict[str, int]] = None,
        context_warn_threshold: Optional[int] = DEFAULT_CODING_AGENT_CONFIG.harness.context_warn_threshold,
        context_compact_threshold: Optional[int] = DEFAULT_CODING_AGENT_CONFIG.harness.context_compact_threshold,
        compaction_keep_recent: int = DEFAULT_CODING_AGENT_CONFIG.harness.compaction_keep_recent,
        tool_result_max_chars: Optional[int] = DEFAULT_CODING_AGENT_CONFIG.harness.tool_result_max_chars,
        tool_result_keep_recent: int = DEFAULT_CODING_AGENT_CONFIG.harness.tool_result_keep_recent,
        context_target_tokens: Optional[int] = DEFAULT_CODING_AGENT_CONFIG.harness.context_target_tokens,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.control_plane = control_plane or NullControlPlane()
        self.config = config or DEFAULT_CODING_AGENT_CONFIG
        if config is not None:
            max_turns = config.harness.max_turns
            max_tool_calls = config.harness.max_tool_calls
            max_runtime_seconds = config.harness.max_runtime_seconds
            max_tokens = config.harness.max_tokens
            context_limits = config.harness.context_limits
            context_warn_threshold = config.harness.context_warn_threshold
            context_compact_threshold = config.harness.context_compact_threshold
            compaction_keep_recent = config.harness.compaction_keep_recent
            tool_result_max_chars = config.harness.tool_result_max_chars
            tool_result_keep_recent = config.harness.tool_result_keep_recent
            context_target_tokens = config.harness.context_target_tokens
        if auto_approve is True:
            set_mode = getattr(self.control_plane, "set_approval_mode", None)
            if callable(set_mode):
                set_mode("always_allow")
        self.registry = registry
        self.session_id = session_id or str(uuid.uuid4())
        self.persistence = persistence or SqlitePersistence(
            self.workspace / ".symphony" / "sessions.sqlite3"
        )
        self.base_system_prompt = system_prompt.rstrip()
        self.mode = mode
        self.plan_store = PlanStore(self.workspace)
        learning_enabled = (
            self.config.learning.enabled if enable_learning is None else enable_learning
        )
        self.learning_store = LearningStore(
            self.workspace,
            max_lessons=self.config.learning.max_lessons,
        )
        self.learning_loop = (
            LearningLoop(
                self.learning_store,
                registry=registry,
                model_id=model_id,
                max_output_tokens=self.config.learning.max_output_tokens,
            )
            if learning_enabled
            else None
        )
        self.tools = tools if tools is not None else build_tools(
            self.workspace,
            config=self.config.tools,
        )
        self.harness = CoreHarness(
            registry=registry,
            model_id=model_id,
            system_prompt=self.base_system_prompt + "\n",
            tools=self.tools,
            control_plane=self.control_plane,
            persistence=self.persistence,
            session_id=self.session_id,
            config=self.config.harness if config is not None else None,
            max_turns=max_turns,
            max_tool_calls=max_tool_calls,
            max_runtime_seconds=max_runtime_seconds,
            max_tokens=max_tokens,
            context_limits=context_limits,
            context_warn_threshold=context_warn_threshold,
            context_compact_threshold=context_compact_threshold,
            compactor=(
                KeepSystemRecentCompactor(
                    keep_recent=compaction_keep_recent,
                    target_tokens=context_target_tokens,
                    keep_recent_tool_results=tool_result_keep_recent,
                )
                if context_compact_threshold is not None
                else None
            ),
            tool_result_max_chars=tool_result_max_chars,
            tool_result_keep_recent=tool_result_keep_recent,
            context_target_tokens=context_target_tokens,
        )
        if tools is None:
            self.harness.register_tool(
                self.harness.make_spawn_tool(configure=self._spawn_child_config)
            )

    def _spawn_child_config(
        self,
        *,
        prompt: str = "",
        label: str = "",
        model_id: Optional[str] = None,
        max_turns: Optional[int] = None,
        **_: Any,
    ) -> ChildConfig:
        """Children run without approval prompts on a forked plane."""
        del prompt, label
        cap = self.harness.config.spawn_max_turns
        turns = None
        if max_turns:
            turns = max(1, min(int(max_turns), cap))
        mid = str(model_id).strip() if model_id else None
        plane = self.control_plane
        fork = getattr(plane, "fork", None)
        child_plane = None
        if callable(fork):
            parent_approvals = getattr(plane, "approvals", None)
            approvals = None
            if parent_approvals is not None:
                approvals = parent_approvals.model_copy(update={"mode": "always_allow"})
            child_plane = fork(approvals=approvals)
        return ChildConfig(model_id=mid or None, max_turns=turns, control_plane=child_plane)

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
        lessons = (
            self.learning_store.context_for(
                task_text,
                limit=self.config.learning.context_limit,
                max_chars=self.config.learning.context_max_chars,
            )
            if self.learning_loop
            else ""
        )
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
        compacted = await KeepSystemRecentCompactor(
            keep_recent=keep_recent,
            target_tokens=self.harness.context_target_tokens,
            keep_recent_tool_results=self.harness.tool_result_keep_recent,
        ).compact(
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

    async def context_report(self) -> ContextReport:
        """Stored conversation vs the payload that would be sent to the model."""
        messages = await self.persistence.load_conversation(session_id=self.session_id)
        return build_context_report(
            messages,
            context_limit=self.harness.state.context_limit(self.harness.model_id),
            keep_recent_tool_results=self.harness.tool_result_keep_recent,
        )


def build_agent(
    *,
    workspace: Union[str, Path],
    control_plane: Optional[ControlPlane] = None,
    model_id: Optional[str] = None,
    session_id: Optional[str] = None,
    enable_learning: Optional[bool] = None,
    config: Optional[CodingAgentConfig | None] = None,
) -> CodingAgent:
    """Build a coding agent from whatever provider credentials are available."""
    from core_ai import build_default_registry, default_model_id

    registry = build_default_registry()
    resolved_config = config or load_coding_agent_config(workspace)
    return CodingAgent(
        registry=registry,
        model_id=default_model_id(registry, model_id),
        workspace=workspace,
        control_plane=control_plane,
        session_id=session_id,
        enable_learning=enable_learning,
        config=resolved_config,
    )
