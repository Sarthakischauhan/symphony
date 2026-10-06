"""Start ``symphony run`` in its own session and return at once (no daemon manager)."""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from coding_agent.addons.persistence import JsonlPersistence, sessions_dir
from coding_agent.addons.persistence.artifacts import publish


def detach(run_argv: list[str], workspace: Path) -> int:
    """Re-exec ``run`` minus ``--detach`` with a pre-generated session id; write ``<sid>/run.json``."""
    session_id = str(uuid.uuid4())
    root = JsonlPersistence(sessions_dir(workspace)).session_dir(session_id)
    root.mkdir(parents=True, exist_ok=True)
    log_path = root / "run.log"
    command = [sys.executable, "-m", "coding_agent.tui", "run", *run_argv, "--session-id", session_id]
    with log_path.open("ab") as log:
        proc = subprocess.Popen(
            command, start_new_session=True, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT
        )
    info = {
        "pid": proc.pid,
        "session_id": session_id,
        "log": str(log_path),
        "workspace": str(workspace),
        "argv": command,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    publish(root / "run.json", (json.dumps(info, indent=2) + "\n").encode("utf-8"))
    print(f"pid {proc.pid}\nlog {log_path}\nsession {session_id}")
    return 0
