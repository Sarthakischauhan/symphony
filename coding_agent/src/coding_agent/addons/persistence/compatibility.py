"""Fail closed when resuming sessions saved with retired execution modes."""

import json
from pathlib import Path
from uuid import UUID

from coding_agent.config import symphony_dir
from coding_agent.addons.persistence.artifacts import safe_path


def validate_session_workflow(directory: Path | None, session_id: str) -> None:
    """Check before any model/tool execution, including direct and headless runs.

    Never rewrite saved state or delete the user's archived plans. The bundle
    takes precedence over the legacy protocol state, as in protocol loading.
    """
    path = safe_path(directory, "state.json") if directory is not None else None
    if path is None or not path.exists():
        try:
            path = symphony_dir() / "protocols" / f"{UUID(session_id)}.json"
        except ValueError:
            return
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("mode", "build") != "build":
        raise ValueError(
            "This session was saved with a removed or unsupported mode. "
            "It cannot be resumed safely; explicitly start a fresh session."
        )
