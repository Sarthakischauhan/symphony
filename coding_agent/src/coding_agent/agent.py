"""Coding agent built on core_harness."""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any, Callable, List, Optional, Union

from core_ai.content import text_from_content
from core_ai.registry import ModelRegistry
from core_ai.types import Content, Message
from core_harness import (
    ChildConfig,
    ControlPlaneEventType,
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

from coding_agent.addons import (
    ApprovalAddon,
    JevAddon,
    LearningAddon,
    SessionMemoryAddon,
    SkillsAddon,
    ai_compaction_from_config,
    jev_from_config,
    langfuse_from_config,
)
from coding_agent.config import (
    CompactionConfig,
    EvaluationConfig,
    LangfuseConfig,
    SettingsSource,
    ensure_spawn_settings,
    resolve_coding_agent_config,
)
from coding_agent.addons.evaluation import JEV_SYSTEM_SEGMENT
from coding_agent.addons.learning import LearningLoop, LearningStore
from coding_agent.tools.memory import MemoryGetTool, MemorySearchTool, MemoryTool
from coding_agent.addons.persistence import JsonlPersistence, sessions_dir
from coding_agent.config.personalities import compose_system_prompt
from coding_agent.addons.plugins import LoadedPlugin, PluginManager
from coding_agent.config.prompts import SYSTEM_PROMPT
from coding_agent.addons.skills import SkillRegistry, bundled_skills_root
from coding_agent.addons.manager import UserAddonRuntime, load_user_addons
from core_harness.extensions import EMPTY_SNAPSHOT
from coding_agent.tools import BashJobs, build_tools


def default_addons(
    *,
    persistence: Persistence,
    harness_config: HarnessConfig,
    compaction: Optional[CompactionConfig] = None,
    spawn_configure: Any = None,
    include_subagent: bool = True,
    langfuse: Optional[LangfuseConfig] = None,
    evaluation: Optional[EvaluationConfig] = None,
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
        self.unattended = self.config.unattended
        self.learning_store = LearningStore(
            self.workspace,
            session_id=self.session_id,
            max_lessons=self.config.learning.max_lessons,
            session_dir=(self.persistence.session_dir(self.session_id)
                         if isinstance(self.persistence, JsonlPersistence) else None),
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
            ("bundled", bundled_skills_root()),
            ("user", Path.home() / ".symphony" / "skills"),
            *[("configured", root) for root in self.config.skills.roots],
        ]
        plugin_addons = []
        self.plugin_diagnostics = ()
        self.loaded_plugins: tuple[LoadedPlugin, ...] = ()
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
            plugin_addons, plugin_skill_roots, self.loaded_plugins, self.plugin_diagnostics = (
                plugin_manager.load(plugin_entries)
            )
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
        self.bash_jobs = BashJobs(
            sessions_dir(self.workspace) / "jobs",
            max_seconds=self.config.tools.bash.max_background_seconds,
        )
        self.tools = tools if tools is not None else build_tools(
            self.workspace,
            config=self.config.tools,
            learning_enabled=self.config.learning.enabled,
            unattended=self.unattended,
            bash_jobs=self.bash_jobs,
            learning_store=self.learning_store,
        )
        for tool in self.tools:
            if isinstance(tool, (MemoryTool, MemorySearchTool, MemoryGetTool)):
                tool.learning_store = self.learning_store
        include_subagent = tools is None
        addons = default_addons(
            persistence=self.persistence,
            harness_config=self.config.harness,
            compaction=self.config.compaction,
            spawn_configure=self._spawn_child_config if include_subagent else None,
            include_subagent=include_subagent,
            langfuse=self.config.langfuse,
            evaluation=self.config.evaluation,
            learning=self.learning_loop,
        )
        self.approval = ApprovalAddon(
            self.workspace, self.sink, approvals=self.config.approvals, unattended=self.unattended
        )
        addons.append(self.approval)
        if self.config.skills.enabled:
            addons.append(SkillsAddon(str(self.workspace), self.skill_registry))
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
        # User addons come last so built-in names (tools, commands, addons) win
        # and the tool list keeps one order across reloads.
        self.user_addons = UserAddonRuntime(
            builtin_tool_names=tuple(self.harness.tools),
            reserved_names=tuple(addon.name for addon in self.harness.addons),
            loader=load_user_addons if include_subagent else lambda _names: EMPTY_SNAPSHOT,
        )
        self._install_addon_tools()
        self._unsubscribe_addons = self.sink.subscribe(self.user_addons.on_event)
        self._active_runs = 0
        self.apply_system_prompt()

    def _install_addon_tools(self) -> None:
        for tool in self.user_addons.surface.tools:
            self.harness.register_tool(tool)
            self.tools.append(tool)

    def _remove_addon_tools(self) -> None:
        addon_tools = self.user_addons.surface.tools
        for tool in addon_tools:
            self.harness.tools.pop(tool.name, None)
        self.tools[:] = [tool for tool in self.tools if all(tool is not item for item in addon_tools)]

    def reload_user_addons(self) -> str:
        """Rebuild user addons between turns; queue the reload during a run."""
        if self._active_runs:
            self.user_addons.reload_pending = True
            return "Addon reload queued · it applies when the current run ends."
        surface = self.user_addons.build()
        self._remove_addon_tools()
        notice = self.user_addons.swap(surface)
        self._install_addon_tools()
        return notice

    def dispose_user_addons(self) -> None:
        """Detach this agent's user addons (the TUI rebuilds the agent on /reload)."""
        self._unsubscribe_addons()
        self.user_addons.dispose()

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
        turns = max(1, int(max_turns)) if max_turns else None
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
        addons = default_addons(
            persistence=self.persistence, harness_config=parent.config,
            compaction=self.config.compaction, include_subagent=False,
            langfuse=self.config.langfuse,
        )
        addons.append(SessionMemoryAddon(
            lambda session_id: LearningStore(
                self.workspace, max_lessons=self.config.learning.max_lessons,
                session_dir=(self.persistence.session_dir(session_id)
                             if isinstance(self.persistence, JsonlPersistence) else None),
            ),
            context_limit=self.config.learning.context_limit,
            context_max_chars=self.config.learning.context_max_chars,
            should_inject=self.config.learning.enabled,
        ))
        gate = self.approval.fork_for_child(parent)
        return addons + ([gate] if gate is not None else [])

    async def run(
        self,
        user_input: Content,
        *,
        conversation: Optional[List[Message]] = None,
        session_id: Optional[str] = None,
    ) -> HarnessResult:
        """Run the agent. Rejected OAuth tokens are refreshed inside the provider."""
        # UI/protocol state must not be bypassed by direct API or headless resume.
        from coding_agent.addons.persistence.compatibility import validate_session_workflow

        effective_session = session_id or self.session_id
        directory = (self.persistence.session_dir(effective_session)
                     if isinstance(self.persistence, JsonlPersistence) else None)
        await asyncio.to_thread(validate_session_workflow, directory, effective_session)
        self._active_runs += 1
        try:
            return await self._run_turns(user_input, conversation=conversation, session_id=session_id)
        finally:
            self._active_runs -= 1
            if not self._active_runs and self.user_addons.reload_pending:
                self.user_addons.reload_pending = False
                notice = self.reload_user_addons()
                await self.sink.emit(ControlPlaneEventType.CONFIG_CHANGED, {"addons": notice})

    async def _run_turns(
        self,
        user_input: Content,
        *,
        conversation: Optional[List[Message]] = None,
        session_id: Optional[str] = None,
    ) -> HarnessResult:
        if isinstance(self.persistence, JsonlPersistence):
            directory = self.persistence.session_dir(session_id or self.session_id)
            if self.learning_store.session_dir != directory.resolve():
                if self.learning_loop is not None:
                    self.learning_loop.cancel()
                    await self.learning_loop.wait()
                self.learning_store = LearningStore(
                    self.workspace, session_id=session_id or self.session_id,
                    max_lessons=self.config.learning.max_lessons,
                    session_dir=directory,
                )
                if self.learning_loop is not None:
                    self.learning_loop.store = self.learning_store
                for tool in self.tools:
                    if isinstance(tool, (MemoryTool, MemorySearchTool, MemoryGetTool)):
                        tool.learning_store = self.learning_store
        task_text = text_from_content(user_input)
        self.apply_system_prompt()
        jev_addon = self.harness.find_addon(JevAddon)
        if jev_addon is not None:
            jev_addon.follow_ups = 0

        if not self.goal:
            goal = getattr(self.persistence, "checkpoint_goal", None)
            if callable(goal):
                self.goal = await asyncio.to_thread(goal, session_id or self.session_id)
            self.goal = self.goal or task_text
        try:
            result = await self.harness.run(
                user_input,
                conversation=conversation,
                session_id=session_id or self.session_id,
            )
        except BaseException:
            # Persisted partial context is available even when the turn stopped.
            # Capture is fail-open and may be retried from its durable job later.
            if self.learning_loop is not None:
                try:
                    partial = await self.persistence.load_conversation(session_id=session_id or self.session_id)
                    self.learning_loop.capture(task_text, partial)
                except Exception:
                    pass
            raise
        follow_up = self._jev_follow_up()
        if follow_up:
            result = await self.harness.run(
                follow_up,
                conversation=result.messages,
                session_id=session_id or self.session_id,
            )
        return result

    def _checkpoint_metadata(self) -> dict[str, Any]:
        """Goal (first prompt) and live background jobs."""
        return {"goal": self.goal, "background_jobs": self.bash_jobs.running()}

    def _jev_follow_up(self) -> Optional[str]:
        addon = self.harness.find_addon(JevAddon)
        if addon is None:
            return None
        prompt = addon.consume_follow_up()
        return prompt if isinstance(prompt, str) and prompt.strip() else None

    def apply_system_prompt(self) -> None:
        """Recompose ``harness.system_prompt`` from base, Jev, and personality."""
        skills = ""
        if self.config.skills.enabled and self.skill_registry.skills:
            lines = [
                "Available skills (load one with the skill tool when it applies):"
            ]
            lines.extend(skill.catalog_line() for skill in self.skill_registry.skills)
            skills = "\n".join(lines)
        self.harness.system_prompt = compose_system_prompt(
            self.base_system_prompt,
            self.config.personality,
            skills=skills,
            jev=JEV_SYSTEM_SEGMENT if self.config.evaluation.enabled else "",
        )

    async def wait_for_learning(self) -> None:
        """Drain the current memory capture worker; failed jobs remain durable."""
        if self.learning_loop is not None:
            await self.learning_loop.wait()

    async def shutdown_learning(self) -> None:
        """Stop capture execution without discarding durable jobs."""
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
    client: str = "",
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
    agent = CodingAgent(
        registry=registry,
        model_id=default_model_id(registry, model_id or resolved.last_model),
        workspace=workspace,
        sink=sink,
        session_id=session_id,
        config=resolved,
        persistence=JsonlPersistence(sessions_dir(workspace, client=client)),
    )
    agent.persistence.client = client
    return agent
