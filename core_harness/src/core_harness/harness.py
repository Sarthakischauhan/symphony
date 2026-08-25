"""Public harness configuration and entry point for executing agent runs."""

from typing import Any, Dict, List, Optional

from core_ai.registry import ModelRegistry
from core_ai.types import Content, Message

from core_harness.control_plane import ControlPlane, NullControlPlane
from core_harness.errors import HarnessCancelled, HarnessLimitExceeded
from core_harness.models.harness import HarnessResult, RunLimits
from core_harness.persistence import NullPersistence, Persistence
from core_harness.run import HarnessRun
from core_harness.state import Compactor, HarnessState
from core_harness.tools import Tool


class CoreHarness:
    """Configured public façade that creates and starts individual runs."""

    def __init__(
        self,
        *,
        registry: ModelRegistry,
        model_id: str,
        system_prompt: str,
        tools: Optional[List[Tool]] = None,
        control_plane: Optional[ControlPlane] = None,
        persistence: Optional[Persistence] = None,
        session_id: Optional[str] = None,
        max_turns: int = 8,
        max_tool_calls: Optional[int] = None,
        max_runtime_seconds: Optional[float] = None,
        max_tokens: Optional[int] = None,
        limits: Optional[RunLimits] = None,
        context_limits: Optional[Dict[str, int]] = None,
        context_warn_threshold: Optional[int] = None,
        context_compact_threshold: Optional[int] = None,
        compactor: Optional[Compactor] = None,
        tool_result_max_chars: Optional[int] = 12_000,
        context_target_tokens: Optional[int] = None,
    ) -> None:
        self.registry = registry
        self.model_id = model_id
        self.system_prompt = system_prompt
        self.control_plane = control_plane or NullControlPlane()
        self.persistence = persistence or NullPersistence()
        self.session_id = session_id
        self.limits = limits or RunLimits(
            max_turns=max_turns,
            max_tool_calls=max_tool_calls,
            max_runtime_seconds=max_runtime_seconds,
            max_tokens=max_tokens,
        )
        self.max_turns = self.limits.max_turns
        if tool_result_max_chars is not None and tool_result_max_chars < 1:
            raise ValueError("tool_result_max_chars must be positive or None")
        self.tool_result_max_chars = tool_result_max_chars
        self.context_target_tokens = context_target_tokens
        self.state = HarnessState(
            context_limits=context_limits,
            context_warn_threshold=context_warn_threshold,
            context_compact_threshold=context_compact_threshold,
            compactor=compactor,
            context_target_tokens=self.context_target_tokens,
        )
        self.tools: Dict[str, Tool] = {}
        for tool in tools or []:
            self.register_tool(tool)

    def register_tool(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def tool_schemas(self) -> List[Dict[str, Any]]:
        return [tool.get_schema() for tool in self.tools.values()]

    async def run(
        self,
        user_input: Content,
        *,
        conversation: Optional[List[Message]] = None,
        session_id: Optional[str] = None,
    ) -> HarnessResult:
        """Start one run with the configured providers, tools, and policies."""
        run = HarnessRun(
            registry=self.registry,
            model_id=self.model_id,
            system_prompt=self.system_prompt,
            tools=self.tools,
            tool_schemas=self.tool_schemas(),
            control_plane=self.control_plane,
            persistence=self.persistence,
            default_session_id=self.session_id,
            limits=self.limits,
            state=self.state,
            tool_result_max_chars=self.tool_result_max_chars,
            context_target_tokens=self.context_target_tokens,
        )
        return await run.execute(
            user_input,
            conversation=conversation,
            session_id=session_id,
        )


__all__ = ["CoreHarness", "HarnessCancelled", "HarnessLimitExceeded"]
