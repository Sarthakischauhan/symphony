"""Build/plan mode selection and mode-picker behavior."""

from __future__ import annotations

from typing import Any

from coding_agent.tui.commands import MODE_CATALOG, find_mode


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
