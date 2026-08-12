"""Status slash-command behavior."""

from __future__ import annotations

from typing import Any


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
        f"session   {app._agent.session_id}\n"
        f"context   {context}\n"
        f"current   {metrics.tokens_used:,} tokens\n"
        f"cumulative input   {metrics.cumulative_tokens:,} tokens"
    )
