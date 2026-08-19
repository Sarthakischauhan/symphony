"""Environment and agent reload behavior."""

from __future__ import annotations

from typing import Any

from dotenv import load_dotenv

from coding_agent.tui.agent_factory import build_agent


async def reload_project(app: Any) -> None:
    """Reload environment-backed agent configuration in the current session."""
    previous_agent = app._agent
    session_id = previous_agent.session_id if previous_agent is not None else app.session_id
    try:
        load_dotenv(override=True)
        reloaded_agent = build_agent(
            workspace=app.workspace,
            control_plane=app.control_plane,
            model_id=app.model_id,
            session_id=session_id,
            enable_learning=app.enable_learning,
        )
        reloaded_agent.set_mode(app.mode)
        app._agent = reloaded_agent
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
