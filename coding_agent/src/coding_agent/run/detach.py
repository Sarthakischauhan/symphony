"""Start ``symphony run`` in its own session and return at once (no daemon manager)."""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from coding_agent.persistence import sessions_dir


def detach(run_argv: list[str], workspace: Path) -> int:
    """Re-exec ``run`` minus ``--detach`` with a pre-generated session id; write ``<sid>.run.json``."""
    session_id = str(uuid.uuid4())
    root = sessions_dir(workspace)
    log_path = root / f"{session_id}.run.log"
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
    (root / f"{session_id}.run.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    print(f"pid {proc.pid}\nlog {log_path}\nsession {session_id}")
    return 0
