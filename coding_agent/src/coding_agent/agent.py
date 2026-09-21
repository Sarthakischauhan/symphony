"""Coding agent built on core_harness."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Callable, List, Literal, Optional, Union

from core_ai.content import text_from_content
from core_ai.registry import ModelRegistry
from core_ai.types import Content, Message
from core_harness import (
    ChildConfig,
    EventSink,
    CoreHarness,
    HarnessConfig,
    HarnessResult,
    Persistence,
    Tool,
)
from core_harness.addons.persistence import PersistenceAddon
from core_harness.addons.subagent import SubagentAddon
from core_harness.context import ContextReport, build_context_report, estimate_prompt_tokens

from coding_agent.approvals import ApprovalAddon
from coding_agent.credentials import renew_oauth_credentials
from coding_agent.compaction import ai_compaction_from_config
from coding_agent.config import (
    CompactionConfig,
    EvaluationConfig,
    LangfuseConfig,
    SettingsSource,
    ensure_spawn_settings,
    resolve_coding_agent_config,
)
from coding_agent.evaluation import jev_from_config
from coding_agent.langfuse import langfuse_from_config
from coding_agent.learning import LearningAddon, LearningLoop, LearningStore
from coding_agent.persistence import JsonlPersistence, sessions_dir
from coding_agent.personalities import compose_system_prompt
from coding_agent.plan import PlanStore
from coding_agent.plan_mode import PlanModeAddon, PlanModeState
from coding_agent.plugins import PluginManager
from coding_agent.prompts import PLAN_MODE_PROMPT, SYSTEM_PROMPT
from coding_agent.skills import SkillRegistry, SkillsAddon
from coding_agent.tools import EnterPlanModeTool, ExitPlanModeTool, build_tools

AgentMode = Literal["build", "plan"]


def default_addons(
    *,
    persistence: Persistence,
    harness_config: HarnessConfig,
    compaction: Optional[CompactionConfig] = None,
    spawn_configure: Any = None,
    include_subagent: bool = True,
    langfuse: Optional[LangfuseConfig] = None,
    evaluation: Optional[EvaluationConfig] = None,
    plan_store: Optional[PlanStore] = None,
    plan_mode: Optional[PlanModeState] = None,
    learning: Optional[LearningLoop] = None,
    should_review: Optional[Callable[[], bool]] = None,
) -> list:
    """Product defaults: persistence, AI compaction, spawn_agent, Langfuse, Jev, learning.

    Compaction is always ``AiCompactionAddon`` (``InferenceCompactor``); the
    harness template compactor is not mounted by coding_agent. Langfuse is
    mounted when enabled in config; the add-on stays silent without keys.
    Jev critic mode mounts only when ``evaluation.enabled`` is true.
    Learning mounts only when a ``LearningLoop`` is passed; omit it so children
    skip (matches ``LearningAddon.fork_for_child`` → ``None``).
    """
    compaction = compaction or CompactionConfig()
    addons: list = [
        PersistenceAddon(persistence),
        ai_compaction_from_config(harness_config, compaction),
    ]
    if include_subagent:
        addons.append(SubagentAddon(configure=spawn_configure, background=True))
    langfuse_addon = langfuse_from_config(langfuse or LangfuseConfig())
    if langfuse_addon is not None:
        addons.append(langfuse_addon)
    jev_addon = jev_from_config(
        evaluation or EvaluationConfig(),
        plan_store=plan_store,
        plan_mode=plan_mode,
    )
    if jev_addon is not None:
        addons.append(jev_addon)
    if learning is not None:
        addons.append(LearningAddon(learning, should_review=should_review))
    return addons


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
        self.base_system_prompt = system_prompt.rstrip()
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
        skill_roots = [
            ("user", Path.home() / ".symphony" / "skills"),
            *[("configured", root) for root in self.config.skills.roots],
        ]
        plugin_addons = []
        plugin_skill_roots = []
        self.plugin_diagnostics = ()
        if self.config.plugins.enabled:
            # Global config must not be able to authorize executable code.
            # Authorization is supplied by the trusted process environment;
            # config may only select already-authorized plugins.
            trusted_roots = [
                Path(value)
                for value in os.environ.get("SYMPHONY_PLUGIN_AUTHORIZED_ROOTS", "").split(os.pathsep)
                if value
            ]
            plugin_manager = PluginManager(self.workspace, authorized_roots=trusted_roots)
            configured_plugins = tuple(self.config.plugins.entries)
            discovered_plugins = plugin_manager.discover()
            # Explicit entries override auto-discovered paths by resolved path;
            # this keeps the installed layout convenient without losing settings.
            configured_paths = {entry.path.expanduser().resolve() for entry in configured_plugins}
            plugin_entries = configured_plugins + tuple(
                entry for entry in discovered_plugins
                if entry.path.expanduser().resolve() not in configured_paths
            )
            plugin_addons, plugin_skill_roots, self.plugin_diagnostics = plugin_manager.load(plugin_entries)
            if self.plugin_diagnostics:
                details = "; ".join(
                    f"{diagnostic.source}: {diagnostic.message}"
                    for diagnostic in self.plugin_diagnostics
                )
                raise ValueError(f"Plugin loading failed: {details}")
            skill_roots.extend(plugin_skill_roots)
        self.skill_registry, self.skill_diagnostics = SkillRegistry.discover(
            skill_roots,
            max_skills=self.config.skills.max_skills,
        )
        self.tools = tools if tools is not None else build_tools(
            self.workspace,
            config=self.config.tools,
            learning_enabled=self.config.learning.enabled,
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
        addons.append(ApprovalAddon(self.workspace, self.sink))
        if self.config.skills.enabled:
            addons.append(SkillsAddon(str(self.workspace), self.skill_registry))
        self.tools.extend([
            EnterPlanModeTool(self.workspace, self.plan_mode, self),
            ExitPlanModeTool(self.workspace, self.plan_mode),
        ])
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
        """Children share the parent sink and skip ApprovalAddon."""
        del prompt, label
        cap = self.harness.config.spawn_max_turns
        turns = None
        if max_turns:
            turns = max(1, min(int(max_turns), cap))
        mid = str(model_id).strip() if model_id else None
        return ChildConfig(
            model_id=mid or None,
            max_turns=turns,
            sink=self.sink,
            # addon_factory replaces fork_for_child. Omit learning (and Jev):
            # LearningAddon.fork_for_child returns None — children skip observe.
            addon_factory=lambda parent: default_addons(
                persistence=self.persistence, harness_config=parent.config,
                compaction=self.config.compaction, include_subagent=False,
                langfuse=self.config.langfuse,
            ),
        )

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
                session_id=session_id or self.session_id,
            )
        return result

    def _jev_follow_up(self) -> Optional[str]:
        addon = next((item for item in self.harness.addons if getattr(item, "name", "") == "jev"), None)
        consume = getattr(addon, "consume_follow_up", None)
        if not callable(consume):
            return None
        prompt = consume()
        return prompt if isinstance(prompt, str) and prompt.strip() else None

    def apply_system_prompt(self) -> None:
        """Recompose ``harness.system_prompt`` from base, personality, and mode."""
        skills = ""
        if self.config.skills.enabled and self.skill_registry.skills:
            lines = [
                "Available skills (read the listed SKILL.md with read_file when relevant):"
            ]
            lines.extend(
                f"- {skill.skill_id}: {skill.description} "
                f"(SKILL.md: {skill.root / 'SKILL.md'})"
                for skill in self.skill_registry.skills
            )
            skills = "\n".join(lines)
        self.harness.system_prompt = compose_system_prompt(
            self.base_system_prompt,
            self.config.personality,
            plan=PLAN_MODE_PROMPT if self.mode == "plan" else "",
            skills=skills,
        )

    def set_mode(self, mode: AgentMode) -> None:
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
        """Compact the persisted conversation through the harness-mounted compactor.

        Emits ``compaction_started`` / ``compaction_completed`` (``manual`` set)
        with message and estimated token counts, fires ``on_compact`` for the
        other add-ons, and persists the result. Returns
        ``(messages_before, messages_after)``.
        """
        state = self.harness.state
        if state.compactor is None:
            raise RuntimeError("No compactor is mounted on the harness.")
        messages = await self.persistence.load_conversation(session_id=self.session_id)
        before = len(messages)
        if not messages:
            return (0, 0)

        context_limit = state.context_limit(self.harness.model_id)
        tokens_used = estimate_prompt_tokens(messages)
        context_left = (
            max(context_limit - tokens_used, 0) if context_limit is not None else None
        )
        compacted = await state.compact(
            messages,
            turn=0,
            context_limit=context_limit,
            tokens_used=tokens_used,
            context_left=context_left,
            emit=self.sink.emit,
            manual=True,
        )
        await self.harness.notify_addons(
            "on_compact",
            turn=0,
            messages=compacted,
            context_limit=context_limit,
            tokens_used=tokens_used,
            context_left=context_left,
        )
        await self.persistence.save_conversation(
            session_id=self.session_id,
            messages=compacted,
        )
        return (before, len(compacted))

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
        model_id=default_model_id(registry, model_id),
        workspace=workspace,
        sink=sink,
        session_id=session_id,
        config=resolved,
    )
