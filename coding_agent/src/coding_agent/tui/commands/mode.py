"""Build/plan mode lockstep for `/mode`, Tab, and plan-modal actions."""

from __future__ import annotations

from typing import Any

from coding_agent.tui.commands.catalog import MODE_CATALOG, find_mode


def sync_app_mode(app: Any, mode: str, *, plan_path: str | None = None) -> None:
    """Keep TUI mode, agent mode, and the plan-mode gate in lockstep."""
    app.mode = mode
    agent = getattr(app, "_agent", None)
    if agent is not None:
        agent.set_mode(mode)
        plan_state = getattr(agent, "plan_mode", None)
        if plan_state is not None:
            if mode == "plan":
                plan_state.begin(plan_path)
            else:
                plan_state.reset()
    app._update_composer_hint()


def select_mode(app: Any, argument: str) -> None:
    selected = find_mode(argument)
    if selected is None:
        app.add_notice(f"Unknown mode: {argument}. Run /mode to see available modes.", "warning")
        return
    sync_app_mode(app, selected.id)
    app.add_notice(f"Switched to {selected.label} mode", "success")


def show_mode_picker(app: Any) -> None:
    prompt = app.query_one("#prompt")
    prompt.value = "/mode "
    prompt.cursor_position = len(prompt.value)
    app.query_one("#slash-menu").set_modes(MODE_CATALOG, app.mode)


def toggle_mode(app: Any) -> None:
    sync_app_mode(app, "plan" if app.mode == "build" else "build")
