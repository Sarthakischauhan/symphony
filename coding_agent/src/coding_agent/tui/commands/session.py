"""Conversation/session slash-command behavior."""

from __future__ import annotations

import uuid
from typing import Any


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
