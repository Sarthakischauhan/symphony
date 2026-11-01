"""Slash-command handlers and dispatcher."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, Iterable

from core_ai import find_provider, get_model, get_provider
from core_ai.providers.catalog import PROVIDERS, configured_provider_ids
from coding_agent.agent import build_agent
from coding_agent.addons.evaluation.addon import JevAddon
from coding_agent.addons.manager import addons_report, tool_change_notice
from coding_agent.commands.jev_argument import parse_jev_argument
from coding_agent.addons.persistence.jsonl import JsonlPersistence
from coding_agent.addons.persistence.presentation import session_images
from coding_agent.config import ensure_spawn_settings
from coding_agent.config.credentials import OFFLINE_HINT, load_provider_env
from coding_agent.addons.langfuse import ensure_langfuse_installed
from textual.containers import Container
from textual.widgets import Static

from coding_agent.tui.chrome import SessionChrome
from coding_agent.tui.screens.modal import ModalBase, ModalCloseButton, ModalScroll
from coding_agent.tui.theme import CONTENT_MODAL_CSS
from coding_agent.tui.tools.images import ImageAttachment, textual_image
from coding_agent.tui.screens import (
    ContextModal,
    DiffModal,
    ExtensionsModal,
    LangfuseSetupScreen,
    LearningModal,
    ProviderOnboardScreen,
)
from coding_agent.commands.catalog import (
    EFFORT_CATALOG,
    SLASH_COMMANDS,
    EffortOption,
    find_model,
    find_personality,
    model_options,
    personality_options,
)

class SessionModal(ModalBase[None]):
    """Durable session archive, including images saved beside the transcript."""

    CSS = CONTENT_MODAL_CSS

    def __init__(self, report: str, root: Path | None = None) -> None:
        super().__init__()
        self.report = report
        self.root = root

    def compose(self):  # type: ignore[no-untyped-def]
        with Container(id="content-pane", classes="modal-pane"):
            yield ModalCloseButton("Esc", id="modal-close")
            yield Static("Session archive", id="content-title")
            with ModalScroll(id="content-body", classes="modal-body"):
                yield Static(self.report, markup=False)
                for index, path in enumerate(session_images(self.root) if self.root else [], 1):
                    yield Static(f"Image {index} · {path.name}", markup=False)
                    try:
                        image = ImageAttachment.from_path(path, f"[Image {index}]")
                        yield textual_image(image.decoded())
                    except OSError:
                        yield Static("Image is unavailable.")
            yield Static("↑↓ scroll   ·   Esc close", classes="modal-footer")


def open_langfuse_setup(app: Any) -> None:
    """Install the optional SDK if needed, then collect Langfuse credentials."""
    app.run_worker(_open_langfuse_setup(app), exclusive=False)


async def _open_langfuse_setup(app: Any) -> None:
    result = await asyncio.to_thread(ensure_langfuse_installed)
    if result.installed and not result.already_present:
        app.add_notice("Langfuse SDK installed.", "success")
    elif not result.installed:
        app.add_notice(result.message, "error")
    app.push_screen(LangfuseSetupScreen(), lambda saved: _on_langfuse_saved(app, saved))


def _on_langfuse_saved(app: Any, saved: bool | None) -> None:
    app.query_one("#prompt").focus()
    if not saved:
        return
    app.run_worker(_finish_langfuse_setup(app), exclusive=False)


async def _finish_langfuse_setup(app: Any) -> None:
    """Re-check the optional SDK, then reload so the add-on can attach."""
    app.add_notice("Langfuse saved · installing SDK if needed…")
    result = await asyncio.to_thread(ensure_langfuse_installed)
    if result.installed:
        notice = (
            "Langfuse saved · reloading configuration."
            if result.already_present
            else "Langfuse SDK installed · reloading configuration."
        )
        app.add_notice(notice, "success")
    else:
        app.add_notice(f"Langfuse keys saved, but tracing is off · {result.message}", "error")
    await reload_project(app)


def toggle_jev(app: Any, argument: str = "") -> None:
    """Enable or disable critic mode without switching the chat model."""
    current = bool(getattr(getattr(app, "config", None), "evaluation", None) and app.config.evaluation.enabled)
    change = parse_jev_argument(current, argument)
    enabled, rule = change.enabled, change.rule
    app.enable_jev = enabled
    settings = {"enabled": enabled}
    if rule is not None:
        app.jev_rule = rule
    app.config = ensure_spawn_settings(app.workspace, overrides={"evaluation": settings})
    app.run_worker(reload_project(app), exclusive=False)
    if enabled:
        app.add_notice("Jev finish check on" + (f" · rule: {rule}" if rule else "") + ".", "success")
    else:
        app.add_notice("Jev critic mode off.", "success")


# --- model_switcher.py ---
def select_model(app: Any, argument: str) -> None:
    agent = app._agent
    assert agent is not None
    selected = find_model(argument, app._model_options)
    if selected is None:
        app.add_notice(f"Unknown model: {argument}. Run /model to see available models.", "warning")
        return
    agent.harness.model_id = selected.id
    app.config = ensure_spawn_settings(
        app.workspace,
        config=app.config,
        overrides={"last_model": selected.id},
    )
    if not model_supports_effort(selected.id):
        agent.harness.reasoning_effort = None
    if agent.learning_loop is not None:
        agent.learning_loop.model_id = selected.id
    app.model_id = selected.id
    app._ui_state.model_id = selected.id
    app._ui_state.set_context_limit(agent.harness.state.context_limit(selected.id))
    app.query_one("#topbar").set_context(app.workspace, selected.id)
    app._set_status("")
    app.add_update(f"Model switched to {selected.label} · {selected.id}")


def show_model_picker(app: Any) -> None:
    prompt = app.query_one("#prompt")
    prompt.value = "/model "
    prompt.cursor_position = len(prompt.value)
    app.query_one("#slash-menu").set_models(app._model_options, app._agent.harness.model_id)


def select_personality(app: Any, argument: str) -> None:
    selected = find_personality(argument, personality_options())
    if selected is None:
        app.add_notice(
            f"Unknown personality: {argument}. Run /personality to see the catalog.",
            "warning",
        )
        return
    resolved = ensure_spawn_settings(app.workspace, overrides={"personality": selected.id})
    app.config = resolved
    agent = getattr(app, "_agent", None)
    if agent is not None:
        agent.config = resolved
        apply = getattr(agent, "apply_system_prompt", None)
        if callable(apply):
            apply()
    app.add_update(f"Personality set to {selected.label}")


def show_personality_picker(app: Any) -> None:
    prompt = app.query_one("#prompt")
    prompt.value = "/personality "
    prompt.cursor_position = len(prompt.value)
    current = getattr(getattr(app, "config", None), "personality", None) or ""
    app.query_one("#slash-menu").set_personalities(personality_options(), current)

# --- effort_switcher.py ---
def effort_matches(
    value: str,
    efforts: Iterable[EffortOption] = EFFORT_CATALOG,
) -> tuple[EffortOption, ...]:
    needle = value.strip().lower()
    return tuple(
        effort
        for effort in efforts
        if not needle
        or needle in effort.id.lower()
        or needle in effort.label.lower()
    )


def effort_options_for_model(model_id: str) -> tuple[EffortOption, ...]:
    """Return only effort levels advertised by the active model."""
    model = _model_info(model_id)
    if model is None or not model.thinking_level_map:
        return ()

    supported = {
        "none" if level == "off" else level
        for level, provider_value in model.thinking_level_map
        if provider_value is not None
    }
    return tuple(
        option
        for option in EFFORT_CATALOG
        if option.id == "default" or option.id in supported
    )


def _model_info(model_id: str):
    provider, separator, model_name = model_id.partition(":")
    if not separator:
        return None
    return get_model(provider, model_name)


def model_supports_effort(model_id: str) -> bool:
    return bool(effort_options_for_model(model_id))


def select_effort(app: Any, argument: str) -> None:
    value = argument.strip().lower()
    efforts = effort_options_for_model(app._agent.harness.model_id)
    supported = {option.id for option in efforts}
    if value not in supported:
        choices = ", ".join(option.id for option in efforts)
        app.add_notice(f"Unknown effort: {argument}. Choose: {choices}", "warning")
        return
    app._agent.harness.reasoning_effort = None if value == "default" else value
    label = next(option.label for option in efforts if option.id == value)
    app.add_update(f"Reasoning effort set to {label}")


def show_effort_picker(app: Any) -> None:
    efforts = effort_options_for_model(app._agent.harness.model_id)
    if not efforts:
        app.add_notice("The active model does not support effort settings.", "warning")
        return
    prompt = app.query_one("#prompt")
    prompt.value = "/effort "
    prompt.cursor_position = len(prompt.value)
    current = app._agent.harness.reasoning_effort or "default"
    app.query_one("#slash-menu").set_efforts(efforts, current)


# --- reload.py ---
async def reload_project(app: Any) -> None:
    """Reload environment-backed agent configuration in the current session."""
    previous_agent = app._agent
    previous_effort = getattr(
        getattr(previous_agent, "harness", None),
        "reasoning_effort",
        None,
    )
    session_id = previous_agent.session_id if previous_agent is not None else app.session_id
    try:
        load_provider_env(app.workspace)
        reloaded_config = ensure_spawn_settings(app.workspace)
        reloaded_config.unattended = app.config.unattended
        reloaded_agent = build_agent(
            workspace=app.workspace,
            sink=app.sink,
            model_id=app.model_id,
            session_id=session_id,
            enable_learning=app.enable_learning,
            enable_jev=getattr(app, "enable_jev", None),
            config=reloaded_config,
            client="tui",
        )
        from coding_agent.protocols.stdio.commands import load_state

        load_state(reloaded_agent)
        session_rule = getattr(app, "jev_rule", "")
        jev_addon = reloaded_agent.harness.find_addon(JevAddon)
        if jev_addon is not None:
            jev_addon.config.rule = session_rule
        reloaded_model = reloaded_agent.harness.model_id
        reloaded_info = _model_info(reloaded_model)
        reloaded_agent.harness.reasoning_effort = (
            None
            if reloaded_info is not None and not model_supports_effort(reloaded_model)
            else previous_effort
        )
        if previous_agent is not None:
            previous_addons = previous_agent.user_addons.surface.tool_names
            previous_agent.dispose_user_addons()
        else:
            previous_addons = frozenset()
        app._agent = reloaded_agent
        app.config = reloaded_config
        app._model_options = model_options(reloaded_agent.registry.namespaces())
        app.session_id = reloaded_agent.session_id

        if previous_agent is not None and previous_agent.learning_loop is not None:
            previous_agent.learning_loop.cancel()

        model_id = reloaded_agent.harness.model_id
        app._ui_state.model_id = model_id
        context_limit = reloaded_agent.harness.state.context_limit(model_id)
        app._ui_state.set_context_limit(context_limit)
        app.query_one("#topbar").set_context(app.workspace, model_id)
        app._set_status("")
        invalidate = getattr(app, "invalidate_workspace_caches", None)
        if callable(invalidate):
            invalidate()
        app.add_update("Configuration reloaded.")
        surface = reloaded_agent.user_addons.surface
        app.add_notice(f"Addons: {tool_change_notice(previous_addons, surface.tool_names)}")
        for notice in surface.notices:
            app.add_notice(notice, "warning")
        app.query_one("#prompt").focus()
    except Exception as exc:  # noqa: BLE001
        app._agent = previous_agent
        app.add_notice(f"Reload failed · {exc}", "error")


# --- session.py ---
async def start_new_session(app: Any) -> None:
    agent = app._agent
    assert agent is not None
    # Background jobs and subagents belong to the conversation being left. Stop
    # them and drop their queued results so they cannot answer into the new one.
    await agent.harness.shutdown_children()
    agent.harness.drain_child_results()
    session_id = str(uuid.uuid4())
    app.session_id = session_id
    agent.session_id = session_id
    agent.harness.session_id = session_id
    store = getattr(agent, "learning_store", None)
    if store is not None and hasattr(store, "bind_session"):
        persistence = getattr(agent, "persistence", None)
        session_dir = None
        if persistence is not None and hasattr(persistence, "session_dir"):
            session_dir = persistence.session_dir(session_id)
        store.bind_session(session_id, session_dir)
    register = getattr(app, "_register_active_session", None)
    if callable(register):
        register()
    app._ui_state.model_id = agent.harness.model_id
    app.reset_session_chrome(
        SessionChrome(context_limit=agent.harness.state.context_limit(agent.harness.model_id))
    )
    app.action_clear_transcript()
    app.add_notice(f"New conversation · {session_id[:8]}", "success")

# --- status.py ---
def show_status(app: Any) -> None:
    if app._agent is None:
        app.add_notice("Status · offline", "warning")
        return
    metrics = app._ui_state.metrics
    context = "unknown"
    if metrics.context_limit is not None and metrics.context_left is not None:
        context = f"{metrics.context_left:,} / {metrics.context_limit:,} tokens left"
    lines = [
        "Status",
        f"model     {app._agent.harness.model_id}",
    ]
    if model_supports_effort(app._agent.harness.model_id):
        lines.append(f"effort    {app._agent.harness.reasoning_effort or 'default'}")
    lines.extend(
        [
            f"personality {getattr(getattr(app, 'config', None), 'personality', None) or 'stock'}",
            f"approval  {app._agent.approval.approvals.mode}",
            f"session   {app._agent.session_id}",
            f"context   {context}",
            f"current   {metrics.tokens_used:,} tokens",
            f"cumulative input   {metrics.cumulative_tokens:,} tokens",
        ]
    )
    namespaces = app._agent.registry.namespaces()
    if namespaces:
        labels = ", ".join(get_provider(provider_id).label for provider_id in namespaces)
        lines.append(f"providers {labels}")
    app.add_notice("\n".join(lines))


async def show_context(app: Any) -> None:
    if app._agent is None:
        app.add_notice("Context · offline", "warning")
        return
    report = await app._agent.context_report()
    app.push_screen(ContextModal(report))


# --- compact.py ---
async def compact_context(app: Any) -> None:
    """Run the harness-mounted compactor on the saved conversation.

    The agent emits ``compaction_*`` events which the presenter turns into the
    notice and footer metrics; the explicit refresh after the await keeps the
    footer current even when no event changed the chrome snapshot.
    """
    try:
        before, after = await app._agent.compact_conversation()
    except RuntimeError as exc:
        app.add_notice(f"Compact unavailable · {exc}", "warning")
        return
    if before == 0:
        app.add_notice("There is no saved conversation to compact.")
    elif before == after:
        app.add_notice(f"Context is already compact · {after} messages")
    if app._presenter is not None:
        app._presenter.refresh_chrome()


# --- command_manager.py ---
class CommandManager:
    """Parse slash commands and run the matching handler."""

    def __init__(self, app: Any) -> None:
        self.app = app


    async def run(self, value: str) -> None:
        command, _, argument = value[1:].partition(" ")
        command = command.lower().strip()
        argument = argument.strip()
        app = self.app

        if command in {"quit", "exit"}:
            app.exit()
        elif command == "clear":
            app.action_clear_transcript()
        elif command == "help":
            commands = SLASH_COMMANDS
            if app._agent is not None:
                commands = (*commands, *app._agent.user_addons.surface.slash_commands)
            if app._agent is not None and not model_supports_effort(
                app._agent.harness.model_id
            ):
                commands = tuple(item for item in commands if item.name != "effort")
            lines = [f"{item.usage:<24} {item.description}" for item in commands]
            app.add_notice("Slash commands\n" + "\n".join(lines))
        elif command == "status":
            show_status(app)
        elif command == "dashboard":
            app.action_dashboard()
        elif command == "context":
            await show_context(app)
        elif command == "session":
            if app._agent is None:
                app.add_notice(OFFLINE_HINT, "error")
            else:
                from coding_agent.addons.persistence.presentation import session_report

                store = app._agent.persistence
                root = store.session_dir(app._agent.session_id) if isinstance(store, JsonlPersistence) else None
                app.push_screen(SessionModal(await session_report(app._agent), root))
        elif command == "learning":
            agent = getattr(app, "_agent", None)
            try:
                learned = agent.learning_store if agent is not None else None
            except AttributeError:
                learned = None
            app.push_screen(LearningModal(
                app.workspace,
                session_id=getattr(agent, "session_id", None),
                store=learned,
            ))
        elif command in {"installed", "extensions", "plugins", "skills"}:
            agent = app._agent
            skills, plugins = (agent.skill_registry.skills, agent.loaded_plugins) if agent else ((), ())
            app.push_screen(ExtensionsModal(skills, plugins))
        elif command == "effort":
            if app._busy:
                app.add_notice("/effort is unavailable while a turn is running.", "warning")
            elif app._agent is None:
                app.add_notice(OFFLINE_HINT, "error")
            elif not model_supports_effort(app._agent.harness.model_id):
                app.add_notice("The active model does not support effort settings.", "warning")
            elif argument:
                select_effort(app, argument)
            else:
                show_effort_picker(app)
        elif command == "voice":
            from coding_agent.tui.composer.voice_mode import toggle_voice

            toggle_voice(app)
        elif command == "addons":
            if app._agent is None:
                app.add_notice(OFFLINE_HINT, "error")
            else:
                runtime = app._agent.user_addons
                app.add_notice(addons_report(runtime.surface, runtime.hook_failures))
        elif command == "reload" and app._busy:
            app._reload_queued = True
            app.add_notice("Reload queued · it applies when the current run ends.")
        elif app._busy:
            app.add_notice(f"/{command} is unavailable while a turn is running.", "warning")
        elif command == "reload":
            await reload_project(app)
        elif command == "provider":
            open_provider_onboard(app, argument)
        elif command == "langfuse":
            open_langfuse_setup(app)
        elif command == "jev":
            toggle_jev(app, argument)
        elif app._agent is None:
            app.add_notice(OFFLINE_HINT, "error")
        elif command == "new":
            await start_new_session(app)
        elif command == "model":
            select_model(app, argument) if argument else show_model_picker(app)
        elif command == "personality":
            select_personality(app, argument) if argument else show_personality_picker(app)
        elif command == "compact":
            await compact_context(app)
        elif command == "diff":
            app.push_screen(DiffModal(app.workspace))
        elif app._agent.user_addons.surface.command(command) is not None:
            app.add_notice(await app._agent.user_addons.run_command(command, argument) or "")
        else:
            app.add_notice(f"Unknown command: /{command}. Type /help to see commands.", "warning")


def open_provider_onboard(app: Any, argument: str = "") -> None:
    initial = None
    if argument:
        selected = find_provider(argument)
        if selected is None:
            app.add_notice(
                f"Unknown provider: {argument}. Choose {', '.join(spec.id for spec in PROVIDERS)}.",
                "warning",
            )
            return
        initial = selected.id
    app.push_screen(
        ProviderOnboardScreen(app.workspace, initial_provider=initial),
        lambda providers: on_provider_onboard(app, providers),
    )


def on_provider_onboard(app: Any, providers: tuple[str, ...] | None) -> None:
    if providers is None:
        app.query_one("#prompt").focus()
        return
    current = set(configured_provider_ids())
    if not current:
        if app._agent is None:
            app.add_notice(OFFLINE_HINT, "warning")
        return
    app.run_worker(reload_after_provider(app), exclusive=False)


async def reload_after_provider(app: Any) -> None:
    from coding_agent.tui.commands.manager import reload_project

    await reload_project(app)
    current = configured_provider_ids()
    if not current:
        return
    labels = ", ".join(get_provider(provider_id).label for provider_id in current)
    app.add_update(f"Providers ready · {labels}. Use /model to switch.")
