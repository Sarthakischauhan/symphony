"""Coding agent built on core_harness."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, List, Literal, Optional, Union

from core_ai.content import text_from_content
from core_ai.registry import ModelRegistry
from core_ai.types import Content, Message
from core_harness import ChildConfig, CoreHarness, EventSink, HarnessResult, Persistence, Tool
from core_harness.context import ContextReport, build_context_report

from coding_agent.approvals import ApprovalAddon
from coding_agent.credentials import renew_oauth_credentials
from coding_agent.config import SettingsSource, ensure_spawn_settings, resolve_coding_agent_config
from coding_agent.default_addons import default_addons
from coding_agent.evaluation import JEV_SYSTEM_SEGMENT
from coding_agent.learning import LearningLoop, LearningStore
from coding_agent.manual_compaction import compact_persisted_conversation
from coding_agent.persistence import JsonlPersistence, sessions_dir
from coding_agent.personalities import compose_system_prompt
from coding_agent.plan import PlanStore
from coding_agent.plan_mode import PlanModeAddon, PlanModeState
from coding_agent.plugins import LoadedPlugin, load_authorized_plugins
from coding_agent.prompts import PLAN_MODE_PROMPT, SYSTEM_PROMPT
from coding_agent.skills import SkillRegistry, SkillsAddon, default_skill_roots
from coding_agent.tools import BashJobs, EnterPlanModeTool, ExitPlanModeTool, build_tools

AgentMode = Literal["build", "plan"]


class CodingAgent:
    """Workspace tools, persisted conversation, and optional post-run learning."""

    def __init__(
        self,
        *,
        registry: ModelRegistry,
        model_id: str,
        workspace: Union[str, Path],
        config: SettingsSource | None = None,
        sink: Optional[EventSink] = None,
        persistence: Optional[Persistence] = None,
        session_id: Optional[str] = None,
        system_prompt: str = SYSTEM_PROMPT,
        mode: AgentMode = "build",
        tools: Optional[List[Tool]] = None,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        loaded = None if config is None else resolve_coding_agent_config(config)
        self.config = ensure_spawn_settings(self.workspace, config=loaded)
        self.sink = sink or EventSink()
        self.registry = registry
        self.session_id = session_id or str(uuid.uuid4())
        self.persistence = persistence or JsonlPersistence(sessions_dir(self.workspace))
        self.goal = ""
        if isinstance(self.persistence, JsonlPersistence):
            self.persistence.checkpoint_metadata = self._checkpoint_metadata
        self.base_system_prompt = system_prompt.rstrip()
        # Unattended runs cannot enter plan mode: approving a plan needs a human.
        self.unattended = self.config.unattended
        mode = "build" if self.unattended else mode
        self.mode = mode
        self.plan_mode = PlanModeState(workspace=self.workspace, active=mode == "plan")
        self.plan_store = PlanStore(self.workspace)
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
                context_limit=self.config.learning.context_limit,
                context_max_chars=self.config.learning.context_max_chars,
            )
            if self.config.learning.enabled
            else None
        )
        skill_roots = default_skill_roots(self.config.skills)
        plugin_addons = []
        self.plugin_diagnostics = ()
        self.loaded_plugins: tuple[LoadedPlugin, ...] = ()
        if self.config.plugins.enabled:
            result = load_authorized_plugins(self.workspace, self.config.plugins)
            plugin_addons, self.loaded_plugins = result.addons, result.plugins
            skill_roots.extend(result.skill_roots)
        self.skill_registry, self.skill_diagnostics = SkillRegistry.discover(
            skill_roots,
            max_skills=self.config.skills.max_skills,
        )
        self.bash_jobs = BashJobs(
            sessions_dir(self.workspace) / "jobs",
            max_seconds=self.config.tools.bash.max_background_seconds,
        )
        self.tools = (
            tools
            if tools is not None
            else build_tools(
                self.workspace,
                config=self.config.tools,
                learning_enabled=self.config.learning.enabled,
                unattended=self.unattended,
                bash_jobs=self.bash_jobs,
            )
        )
        include_subagent = tools is None
        addons = default_addons(
            persistence=self.persistence,
            harness_config=self.config.harness,
            compaction=self.config.compaction,
            spawn_configure=self._spawn_child_config if include_subagent else None,
            include_subagent=include_subagent,
            langfuse=self.config.langfuse,
            evaluation=self.config.evaluation,
            plan_store=self.plan_store,
            plan_mode=self.plan_mode,
            learning=self.learning_loop,
            should_review=lambda: self.mode != "plan",
        )
        addons.append(PlanModeAddon(self.plan_mode))
        self.approval = ApprovalAddon(
            self.workspace, self.sink, approvals=self.config.approvals, unattended=self.unattended
        )
        addons.append(self.approval)
        if self.config.skills.enabled:
            addons.append(SkillsAddon(str(self.workspace), self.skill_registry))
        if not self.unattended:
            self.tools.extend(
                [
                    EnterPlanModeTool(self.workspace, self.plan_mode, self),
                    ExitPlanModeTool(self.workspace, self.plan_mode),
                ]
            )
        self.harness = CoreHarness(
            registry=registry,
            model_id=model_id,
            system_prompt=self.base_system_prompt + "\n",
            config=self.config.harness,
            tools=self.tools,
            sink=self.sink,
            session_id=self.session_id,
            agent_id=self.session_id,
            addons=addons + plugin_addons,
        )
        self.bash_jobs.bind(self.harness)
        self.apply_system_prompt()

    def _spawn_child_config(
        self,
        *,
        prompt: str = "",
        label: str = "",
        model_id: Optional[str] = None,
        max_turns: Optional[int] = None,
        **_: Any,
    ) -> ChildConfig:
        """Children share the parent sink and skip ApprovalAddon (deny-only fork when unattended)."""
        del prompt, label
        cap = self.harness.config.spawn_max_turns
        turns = None
        if max_turns:
            turns = max(1, int(max_turns))
            if cap is not None:
                turns = min(turns, cap)
        mid = str(model_id).strip() if model_id else None
        return ChildConfig(
            model_id=mid or None,
            max_turns=turns,
            sink=self.sink,
            # addon_factory replaces fork_for_child. Omit learning (and Jev):
            # LearningAddon.fork_for_child returns None — children skip observe.
            addon_factory=self._child_addons,
        )

    def _child_addons(self, parent: CoreHarness) -> list:
        """Children get persistence, compaction, Langfuse, and the forked approval gate; no learning or Jev."""
        addons = default_addons(
            persistence=self.persistence,
            harness_config=parent.config,
            compaction=self.config.compaction,
            include_subagent=False,
            langfuse=self.config.langfuse,
        )
        gate = self.approval.fork_for_child(parent)
        return addons + ([gate] if gate is not None else [])

    async def run(
        self,
        user_input: Content,
        *,
        conversation: Optional[List[Message]] = None,
        session_id: Optional[str] = None,
    ) -> HarnessResult:
        """Run the agent, renewing an OAuth token once after an auth failure."""
        mode = self.mode
        task_text = text_from_content(user_input)
        self.apply_system_prompt()
        jev_addon = self._jev_addon()
        if jev_addon is not None:
            jev_addon.follow_ups = 0

        if not self.goal:
            previous = await self.persistence.load_checkpoint(session_id=session_id or self.session_id)
            self.goal = (previous.metadata.get("goal") if previous else "") or task_text
        if mode == "plan" and not self.plan_mode.plan_path:
            plan_path = self.plan_store.begin(task_text)
            self.plan_mode.begin(str(plan_path))
        try:
            result = await self.harness.run(
                user_input,
                conversation=conversation,
                session_id=session_id or self.session_id,
            )
        except Exception as exc:
            registry = renew_oauth_credentials(self.harness.model_id, exc)
            if registry is None:
                raise
            self.harness.registry = registry
            result = await self.harness.run(
                user_input,
                conversation=conversation,
                session_id=session_id or self.session_id,
            )
        follow_up = self._jev_follow_up()
        if follow_up:
            result = await self.harness.run(
                follow_up,
                conversation=result.messages,
                session_id=session_id or self.session_id,
            )
        return result

    def _checkpoint_metadata(self) -> dict[str, Any]:
        """Goal (first prompt), current todo (the active plan file), live background jobs."""
        return {"goal": self.goal, "todo": self.plan_mode.plan_path, "background_jobs": self.bash_jobs.running()}

    def _jev_addon(self) -> Any:
        """The mounted Jev critic addon, or None when evaluation is off."""
        return next((item for item in self.harness.addons if getattr(item, "name", "") == "jev"), None)

    def _jev_follow_up(self) -> Optional[str]:
        """The critic's follow-up prompt for one more run, or None when it has nothing to add."""
        addon = self._jev_addon()
        consume = getattr(addon, "consume_follow_up", None)
        if not callable(consume):
            return None
        prompt = consume()
        return prompt if isinstance(prompt, str) and prompt.strip() else None

    def apply_system_prompt(self) -> None:
        """Recompose ``harness.system_prompt`` from base, mode, Jev, and personality."""
        skills = self.skill_registry.catalog_prompt() if self.config.skills.enabled else ""
        self.harness.system_prompt = compose_system_prompt(
            self.base_system_prompt,
            self.config.personality,
            plan=PLAN_MODE_PROMPT if self.mode == "plan" else "",
            skills=skills,
            jev=JEV_SYSTEM_SEGMENT if self.config.evaluation.enabled else "",
        )

    def set_mode(self, mode: AgentMode) -> None:
        """Switch build/plan mode; unattended runs always stay in build mode."""
        mode = "build" if self.unattended else mode
        self.mode = mode
        if mode == "plan":
            self.plan_mode.begin()
        else:
            self.plan_mode.reset()
        self.apply_system_prompt()

    async def wait_for_learning(self) -> None:
        """Optionally drain pending reflections before application shutdown."""
        if self.learning_loop is not None:
            await self.learning_loop.wait()

    async def shutdown_learning(self) -> None:
        """Cancel or finish pending reflection when the TUI exits."""
        if self.learning_loop is not None:
            await self.learning_loop.shutdown()

    async def compact_conversation(self) -> tuple[int, int]:
        """Compact the persisted conversation now; see ``compact_persisted_conversation``."""
        return await compact_persisted_conversation(
            self.harness, self.persistence, session_id=self.session_id, emit=self.sink.emit
        )

    async def context_report(self) -> ContextReport:
        """Stored conversation vs the payload that would be sent to the model."""
        messages = await self.persistence.load_conversation(session_id=self.session_id)
        return build_context_report(
            messages,
            context_limit=self.harness.state.context_limit(self.harness.model_id),
        )


def build_agent(
    *,
    workspace: Union[str, Path],
    sink: Optional[EventSink] = None,
    model_id: Optional[str] = None,
    session_id: Optional[str] = None,
    enable_learning: Optional[bool] = None,
    enable_jev: Optional[bool] = None,
    config: Optional[SettingsSource] = None,
) -> CodingAgent:
    """Build a coding agent from whatever provider credentials are available."""
    from core_ai import build_default_registry, default_model_id

    registry = build_default_registry()
    loaded = None if config is None else resolve_coding_agent_config(config)
    overrides: dict[str, Any] = {}
    if enable_learning is not None:
        overrides["learning"] = {"enabled": enable_learning}
    if enable_jev is not None:
        overrides["evaluation"] = {"enabled": enable_jev}
    resolved = ensure_spawn_settings(
        workspace,
        config=loaded,
        overrides=overrides or None,
    )
    return CodingAgent(
        registry=registry,
        model_id=default_model_id(registry, model_id or resolved.last_model),
        workspace=workspace,
        sink=sink,
        session_id=session_id,
        config=resolved,
    )
