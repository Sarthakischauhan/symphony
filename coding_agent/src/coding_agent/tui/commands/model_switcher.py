"""Model selection and model-picker behavior."""

from __future__ import annotations

from typing import Any

from coding_agent.tui.commands import MODEL_CATALOG, find_model


def select_model(app: Any, argument: str) -> None:
    agent = app._agent
    assert agent is not None
    selected = find_model(argument)
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
    app.query_one("#slash-menu").set_models(MODEL_CATALOG, app._agent.harness.model_id)
