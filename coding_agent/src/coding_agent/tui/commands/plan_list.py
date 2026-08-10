"""Plan listing, selection, and plan-modal actions."""

from __future__ import annotations

from typing import Any

from coding_agent.tui.commands import PlanOption
from coding_agent.tui.modal import PlanModal


def plan_options(app: Any, query: str = "") -> tuple[PlanOption, ...]:
    needle = query.strip().lower()
    options: list[PlanOption] = []
    for path in app._plan_store.list_paths():
        task = app._plan_store.task_for(path)
        if needle and needle not in path.name.lower() and needle not in task.lower():
            continue
        options.append(PlanOption(path.name, task, str(path.relative_to(app.workspace))))
    return tuple(options)


def show_plan_picker(app: Any) -> None:
    plans = plan_options(app)
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
