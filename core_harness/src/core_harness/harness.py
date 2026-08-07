"""Public harness configuration and entry point for executing agent runs."""

from typing import Any, Dict, List, Optional

from core_ai.registry import ModelRegistry
from core_ai.types import Message

from core_harness.control_plane import ControlPlane, NullControlPlane
from core_harness.models.harness import HarnessResult
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
        context_limits: Optional[Dict[str, int]] = None,
        context_warn_threshold: Optional[int] = None,
        context_compact_threshold: Optional[int] = None,
        compactor: Optional[Compactor] = None,
    ) -> None:
        self.registry = registry
        self.model_id = model_id
        self.system_prompt = system_prompt
        self.control_plane = control_plane or NullControlPlane()
        self.persistence = persistence or NullPersistence()
        self.session_id = session_id
        self.max_turns = max_turns
        self.state = HarnessState(
            context_limits=context_limits,
            context_warn_threshold=context_warn_threshold,
            context_compact_threshold=context_compact_threshold,
            compactor=compactor,
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
        user_input: str,
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
            max_turns=self.max_turns,
            state=self.state,
        )
        return await run.execute(
            user_input,
            conversation=conversation,
            session_id=session_id,
        )


from core_harness.run import HarnessCancelled

__all__ = ["CoreHarness", "HarnessCancelled"]
