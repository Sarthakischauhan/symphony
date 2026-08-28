"""Slash-command catalogs and handlers for the coding-agent TUI."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from dotenv import load_dotenv

from core_ai import list_models
from coding_agent.agent import build_agent
from coding_agent.config import load_coding_agent_config
from coding_agent.tui.modal import DiffModal, LearningModal, PlanModal

# --- __init__.py ---
@dataclass(frozen=True)
class SlashCommand:
    name: str
    description: str
    argument: str = ""

    @property
    def usage(self) -> str:
        return f"/{self.name}{f' {self.argument}' if self.argument else ''}"


@dataclass(frozen=True)
class ModelOption:
    id: str
    label: str
    description: str


@dataclass(frozen=True)
class ModeOption:
    id: str
    label: str
    description: str


@dataclass(frozen=True)
class PlanOption:
    id: str
    label: str
    description: str


def model_options(providers: Iterable[str] | None = None) -> tuple[ModelOption, ...]:
    """Build TUI choices from the core_ai catalog, optionally by provider."""
    source = list_models() if providers is None else tuple(
        model for provider in providers for model in list_models(provider)
    )
    return tuple(
        ModelOption(
            id=model.full_id,
            label=model.id,
            description=f"{model.provider} · {model.api.replace('_', ' ')}",
        )
        for model in source
    )


def find_model(
    value: str,
    models: Iterable[ModelOption] | None = None,
) -> Optional[ModelOption]:
    models = model_options() if models is None else models
    needle = value.strip().lower()
    if not needle:
        return None
    matches = [
        model for model in models
        if needle in {model.id.lower(), model.id.split(":", 1)[-1].lower(), model.label.lower()}
    ]
    return matches[0] if len(matches) == 1 else None


def model_matches(
    value: str,
    models: Iterable[ModelOption] | None = None,
) -> tuple[ModelOption, ...]:
    models = model_options() if models is None else models
    needle = value.strip().lower()
    return tuple(model for model in models if not needle or needle in model.id.lower() or needle in model.label.lower())


MODE_CATALOG = (
    ModeOption("build", "Build", "Read, edit, and run code"),
    ModeOption("plan", "Plan", "Inspect and write a plan only"),
)

SLASH_COMMANDS = (
    SlashCommand("model", "View or switch the active model", "[model]"),
    SlashCommand("mode", "View or switch between build and plan", "[mode]"),
    SlashCommand("plan", "Choose and open a workspace plan", "[plan]"),
    SlashCommand("new", "Start a fresh conversation"),
    SlashCommand("reload", "Reload configuration from .env"),
    SlashCommand("compact", "Keep recent messages and compact saved context"),
    SlashCommand("status", "Show session, model, and context details"),
    SlashCommand("learning", "Open markdown-rendered agent learnings"),
    SlashCommand("diff", "Open the current workspace diff in a modal"),
    SlashCommand("clear", "Clear the visible transcript"),
    SlashCommand("help", "Show available slash commands"),
    SlashCommand("quit", "Exit Symphony"),
)


def command_matches(value: str) -> tuple[SlashCommand, ...]:
    if not value.startswith("/") or " " in value:
        return ()
    prefix = value[1:].lower()
    return tuple(command for command in SLASH_COMMANDS if command.name.startswith(prefix))



def find_mode(value: str, modes: Iterable[ModeOption] = MODE_CATALOG) -> Optional[ModeOption]:
    needle = value.strip().lower()
    matches = [mode for mode in modes if needle in {mode.id.lower(), mode.label.lower()}]
    return matches[0] if len(matches) == 1 else None


def mode_matches(value: str, modes: Iterable[ModeOption] = MODE_CATALOG) -> tuple[ModeOption, ...]:
    needle = value.strip().lower()
    return tuple(mode for mode in modes if not needle or needle in mode.id.lower() or needle in mode.label.lower())

# --- model_switcher.py ---
def select_model(app: Any, argument: str) -> None:
    agent = app._agent
    assert agent is not None
    selected = find_model(argument, app._model_options)
    if selected is None:
        app.add_notice(f"Unknown model: {argument}. Run /model to see available models.", "warning")
        return
    agent.harness.model_id = selected.id
    if agent.learning_loop is not None:
        agent.learning_loop.model_id = selected.id
    app.model_id = selected.id
    app._ui_state.model_id = selected.id
    app._ui_state.metrics.context_limit = agent.harness.state.context_limit(selected.id)
    app.query_one("#topbar").set_context(app.workspace, selected.id)
    app._set_status("")
    app.add_notice(f"Model switched to {selected.label} · {selected.id}", "success")


def show_model_picker(app: Any) -> None:
    prompt = app.query_one("#prompt")
    prompt.value = "/model "
    prompt.cursor_position = len(prompt.value)
    app.query_one("#slash-menu").set_models(app._model_options, app._agent.harness.model_id)

# --- mode_switcher.py ---
def select_mode(app: Any, argument: str) -> None:
    selected = find_mode(argument)
    if selected is None:
        app.add_notice(f"Unknown mode: {argument}. Run /mode to see available modes.", "warning")
        return
    app.mode = selected.id
    if app._agent is not None:
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
    if action != "build" or app._busy:
        return
    app.mode = "build"
    if app._agent is not None:
        app._agent.set_mode("build")
    app._update_composer_hint()
    prompt = app.query_one("#prompt")
    plan_path = app._plan_store.path.relative_to(app.workspace)
    prompt.value = f"Build the approved plan in {plan_path}."
    prompt.action_submit()

# --- reload.py ---
async def reload_project(app: Any) -> None:
    """Reload environment-backed agent configuration in the current session."""
    previous_agent = app._agent
    session_id = previous_agent.session_id if previous_agent is not None else app.session_id
    try:
        load_dotenv(override=True)
        reloaded_config = load_coding_agent_config(app.workspace)
        reloaded_agent = build_agent(
            workspace=app.workspace,
            control_plane=app.control_plane,
            model_id=app.model_id,
            session_id=session_id,
            enable_learning=app.enable_learning,
            config=reloaded_config,
        )
        reloaded_agent.set_mode(app.mode)
        app._agent = reloaded_agent
        app.config = reloaded_config
        app.control_plane.approvals = reloaded_config.approvals
        app._model_options = model_options(reloaded_agent.registry.namespaces())
        app.session_id = reloaded_agent.session_id

        if previous_agent is not None and previous_agent.learning_loop is not None:
            previous_agent.learning_loop.cancel()

        model_id = reloaded_agent.harness.model_id
        app._ui_state.model_id = model_id
        context_limit = reloaded_agent.harness.state.context_limit(model_id)
        app._ui_state.metrics.context_limit = context_limit
        if app._ui_state.metrics.context_left is not None:
            app._ui_state.metrics.context_left = max(
                context_limit - app._ui_state.metrics.tokens_used, 0
            )
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
    app.add_notice(
        "Status\n"
        f"model     {app._agent.harness.model_id}\n"
        f"mode      {app.mode}\n"
        f"approval  {app.control_plane.approvals.mode}\n"
        f"session   {app._agent.session_id}\n"
        f"context   {context}\n"
        f"current   {metrics.tokens_used:,} tokens\n"
        f"cumulative input   {metrics.cumulative_tokens:,} tokens"
    )

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
            lines = [f"{item.usage:<24} {item.description}" for item in SLASH_COMMANDS]
            app.add_notice("Slash commands\n" + "\n".join(lines))
        elif command == "status":
            show_status(app)
        elif command == "learning":
            app.push_screen(LearningModal(app.workspace))
        elif command == "plan":
            open_plan_modal(app, argument) if argument else show_plan_picker(app)
        elif command == "mode":
            if app._busy:
                app.add_notice("/mode is unavailable while a turn is running.", "warning")
            else:
                select_mode(app, argument) if argument else show_mode_picker(app)
        elif app._busy:
            app.add_notice(f"/{command} is unavailable while a turn is running.", "warning")
        elif command == "reload":
            await reload_project(app)
        elif app._agent is None:
            app.add_notice("Agent is offline. Configure OPENAI_API_KEY and restart.", "error")
        elif command == "new":
            start_new_session(app)
        elif command == "model":
            select_model(app, argument) if argument else show_model_picker(app)
        elif command == "compact":
            before, after = await app._agent.compact_conversation()
            if before == 0:
                app.add_notice("There is no saved conversation to compact.")
            elif before == after:
                app.add_notice(f"Context is already compact · {after} messages")
        elif command == "diff":
            app.push_screen(DiffModal(app.workspace))
        else:
            app.add_notice(f"Unknown command: /{command}. Type /help to see commands.", "warning")

    def open_plan_modal(self, plan_name: str | None = None) -> None:
        open_plan_modal(self.app, plan_name)

    def on_plan_action(self, action: str | None) -> None:
        on_plan_action(self.app, action)

__all__ = [
    "CommandManager",
    "MODE_CATALOG",
    "ModeOption",
    "model_options",
    "ModelOption",
    "PlanOption",
    "SLASH_COMMANDS",
    "SlashCommand",
    "command_matches",
    "find_mode",
    "find_model",
    "mode_matches",
    "model_matches",
    "toggle_mode",
]
