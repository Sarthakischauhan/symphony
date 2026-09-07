"""Slash-command handlers and dispatcher."""

from __future__ import annotations

import uuid
from typing import Any, Iterable

from core_ai import get_model, get_provider
from coding_agent.agent import build_agent
from coding_agent.config import ensure_spawn_settings
from coding_agent.credentials import OFFLINE_HINT, load_provider_env
from coding_agent.tui.screens import ContextModal, DiffModal, ExtensionsModal, LearningModal, PlanModal
from coding_agent.tui.commands.provider import open_provider_onboard
from coding_agent.tui.commands.catalog import (
    EFFORT_CATALOG,
    MODE_CATALOG,
    SLASH_COMMANDS,
    EffortOption,
    PlanOption,
    find_mode,
    find_model,
    model_options,
)

# --- model_switcher.py ---
def select_model(app: Any, argument: str) -> None:
    agent = app._agent
    assert agent is not None
    selected = find_model(argument, app._model_options)
    if selected is None:
        app.add_notice(f"Unknown model: {argument}. Run /model to see available models.", "warning")
        return
    agent.harness.model_id = selected.id
    if not model_supports_effort(selected.id):
        agent.harness.reasoning_effort = None
    if agent.learning_loop is not None:
        agent.learning_loop.model_id = selected.id
    app.model_id = selected.id
    app._ui_state.model_id = selected.id
    app._ui_state.set_context_limit(agent.harness.state.context_limit(selected.id))
    app.query_one("#topbar").set_context(app.workspace, selected.id)
    app._set_status("")
    app.add_notice(f"Model switched to {selected.label} · {selected.id}", "success")


def show_model_picker(app: Any) -> None:
    prompt = app.query_one("#prompt")
    prompt.value = "/model "
    prompt.cursor_position = len(prompt.value)
    app.query_one("#slash-menu").set_models(app._model_options, app._agent.harness.model_id)

# --- mode_switcher.py ---
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
    app.add_notice(f"Reasoning effort set to {label}", "success")


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


def select_mode(app: Any, argument: str) -> None:
    selected = find_mode(argument)
    if selected is None:
        app.add_notice(f"Unknown mode: {argument}. Run /mode to see available modes.", "warning")
        return
    app.mode = selected.id
    if app._agent is not None:
        plan_state = getattr(app._agent, "plan_mode", None)
        if plan_state is not None:
            if app.mode == "plan":
                plan_state.begin()
            else:
                plan_state.reset()
        app._agent.set_mode(app.mode)
    app._update_composer_hint()
    app.add_notice(f"Switched to {selected.label} mode", "success")


def show_mode_picker(app: Any) -> None:
    prompt = app.query_one("#prompt")
    prompt.value = "/mode "
    prompt.cursor_position = len(prompt.value)
    app.query_one("#slash-menu").set_modes(MODE_CATALOG, app.mode)


def toggle_mode(app: Any) -> None:
    app.mode = "plan" if app.mode == "build" else "build"
    if app._agent is not None:
        plan_state = getattr(app._agent, "plan_mode", None)
        if plan_state is not None:
            if app.mode == "plan":
                plan_state.begin()
            else:
                plan_state.reset()
        app._agent.set_mode(app.mode)
    app._update_composer_hint()

# --- plan_list.py ---
def list_plan_options(app: Any, query: str = "") -> tuple[PlanOption, ...]:
    needle = query.strip().lower()
    options: list[PlanOption] = []
    for path in app._plan_store.list_paths():
        task = app._plan_store.task_for(path)
        if needle and needle not in path.name.lower() and needle not in task.lower():
            continue
        options.append(PlanOption(path.name, task, str(path.relative_to(app.workspace))))
    return tuple(options)


def show_plan_picker(app: Any) -> None:
    plans = list_plan_options(app)
    if not plans:
        app.add_notice("No saved plans yet. Switch to Plan mode to create one.")
        return
    prompt = app.query_one("#prompt")
    prompt.value = "/plan "
    prompt.cursor_position = len(prompt.value)
    app.query_one("#slash-menu").set_plans(plans, app._plan_store.path.name)


def open_plan_modal(app: Any, plan_name: str | None = None) -> None:
    if plan_name is not None and app._plan_store.select(plan_name) is None:
        app.add_notice(f"Unknown plan: {plan_name}. Run /plan to choose one.", "warning")
        return
    if not app._plan_store.path.exists():
        app.add_notice("No saved plans yet. Switch to Plan mode to create one.")
        return
    app.push_screen(PlanModal(app.workspace), app._command_manager.on_plan_action)


def on_plan_action(app: Any, action: str | None) -> None:
    if app._busy:
        return
    if action == "quit":
        app.mode = "build"
        if app._agent is not None:
            app._agent.set_mode("build")
        app._update_composer_hint()
        return
    if action == "changes":
        app.mode = "plan"
        app._update_composer_hint()
        app.query_one("#prompt").focus()
        return
    if action != "build":
        return
    app.mode = "build"
    if app._agent is not None:
        plan_state = getattr(app._agent, "plan_mode", None)
        if plan_state is not None:
            plan_state.approve()
        # Approval is consumed by the next build turn; do not reset the gate
        # before the harness has observed it.
        app._agent.mode = "build"
    app._update_composer_hint()
    prompt = app.query_one("#prompt")
    plan_path = app._plan_store.path.relative_to(app.workspace)
    prompt.value = f"Build the approved plan in {plan_path}."
    prompt.action_submit()

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
        reloaded_agent = build_agent(
            workspace=app.workspace,
            sink=app.sink,
            model_id=app.model_id,
            session_id=session_id,
            enable_learning=app.enable_learning,
            config=reloaded_config,
        )
        reloaded_agent.set_mode(app.mode)
        reloaded_model = reloaded_agent.harness.model_id
        reloaded_info = _model_info(reloaded_model)
        reloaded_agent.harness.reasoning_effort = (
            None
            if reloaded_info is not None and not model_supports_effort(reloaded_model)
            else previous_effort
        )
        app._agent = reloaded_agent
        app.config = reloaded_config
        app.sink.approvals = reloaded_config.approvals
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
        app.add_notice("Configuration reloaded.", "success")
        app.query_one("#prompt").focus()
    except Exception as exc:  # noqa: BLE001
        app._agent = previous_agent
        app.add_notice(f"Reload failed · {exc}", "error")


# --- session.py ---
def start_new_session(app: Any) -> None:
    agent = app._agent
    assert agent is not None
    session_id = str(uuid.uuid4())
    app.session_id = session_id
    agent.session_id = session_id
    agent.harness.session_id = session_id
    app._ui_state.reset_for_run(model_id=agent.harness.model_id)
    app._ui_state.phase = "idle"
    app._ui_state.detail = "ready"
    app.action_clear_transcript()
    app.add_notice(f"New conversation · {session_id[:8]}", "success")
    app._set_status("")

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
            f"mode      {app.mode}",
            f"approval  {app.sink.approvals.mode}",
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

    def plan_options(self, query: str = ""):
        return list_plan_options(self.app, query)

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
            if app._agent is not None and not model_supports_effort(
                app._agent.harness.model_id
            ):
                commands = tuple(item for item in commands if item.name != "effort")
            lines = [f"{item.usage:<24} {item.description}" for item in commands]
            app.add_notice("Slash commands\n" + "\n".join(lines))
        elif command == "status":
            show_status(app)
        elif command == "context":
            await show_context(app)
        elif command == "learning":
            app.push_screen(LearningModal(app.workspace))
        elif command in {"installed", "extensions", "plugins", "skills"}:
            app.push_screen(ExtensionsModal(app.workspace, app._agent))
        elif command == "plan":
            if argument:
                open_plan_modal(app, argument)
            else:
                select_mode(app, "plan")
        elif command == "plans":
            open_plan_modal(app, argument) if argument else show_plan_picker(app)
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
        elif command == "mode":
            if app._busy:
                app.add_notice("/mode is unavailable while a turn is running.", "warning")
            else:
                select_mode(app, argument) if argument else show_mode_picker(app)
        elif app._busy:
            app.add_notice(f"/{command} is unavailable while a turn is running.", "warning")
        elif command == "reload":
            await reload_project(app)
        elif command == "provider":
            open_provider_onboard(app, argument)
        elif app._agent is None:
            app.add_notice(OFFLINE_HINT, "error")
        elif command == "new":
            start_new_session(app)
        elif command == "model":
            select_model(app, argument) if argument else show_model_picker(app)
        elif command == "compact":
            await compact_context(app)
        elif command == "diff":
            app.push_screen(DiffModal(app.workspace))
        else:
            app.add_notice(f"Unknown command: /{command}. Type /help to see commands.", "warning")

    def open_plan_modal(self, plan_name: str | None = None) -> None:
        open_plan_modal(self.app, plan_name)

    def on_plan_action(self, action: str | None) -> None:
        on_plan_action(self.app, action)
