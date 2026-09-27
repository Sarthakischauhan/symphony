"""Live registry of Symphony processes that currently own a session.

Resume should not offer a conversation another process is still using. Each
running agent writes one small JSON file under ``~/.symphony/active`` and
removes it on a clean exit. A file whose process is gone is stale and ignored.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def active_dir() -> Path:
    """Directory that holds one registry file per live Symphony process."""
    target = (Path.home() / ".symphony" / "active").expanduser()
    target.mkdir(parents=True, exist_ok=True)
    return target


def _path(pid: int) -> Path:
    return active_dir() / f"{pid}.json"


@dataclass(frozen=True)
class ActiveSession:
    """One Symphony process and the session it currently owns."""

    session_id: str
    pid: int
    kind: str
    workspace: str
    model_id: str = ""
    label: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "pid": self.pid,
            "kind": self.kind,
            "workspace": self.workspace,
            "model_id": self.model_id,
            "label": self.label,
        }


def register_active(
    session_id: str,
    *,
    workspace: str | Path,
    kind: str,
    model_id: str = "",
    label: str = "",
    pid: int | None = None,
) -> ActiveSession:
    """Record that this process owns ``session_id``. Replaces any prior record."""
    record = ActiveSession(
        session_id=session_id,
        pid=os.getpid() if pid is None else pid,
        kind=kind,
        workspace=str(workspace),
        model_id=model_id,
        label=label,
    )
    path = _path(record.pid)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record.as_dict()), encoding="utf-8")
    temporary.replace(path)
    return record


def release_active(pid: int | None = None) -> None:
    """Drop this process's registry file. Missing files are fine."""
    path = _path(os.getpid() if pid is None else pid)
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _load(path: Path) -> ActiveSession | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    session_id = str(payload.get("session_id") or "")
    try:
        pid = int(payload.get("pid") or 0)
    except (TypeError, ValueError):
        return None
    if not session_id or pid <= 0:
        return None
    return ActiveSession(
        session_id=session_id,
        pid=pid,
        kind=str(payload.get("kind") or "agent"),
        workspace=str(payload.get("workspace") or ""),
        model_id=str(payload.get("model_id") or ""),
        label=str(payload.get("label") or ""),
    )


def list_active(*, include_dead: bool = False) -> list[ActiveSession]:
    """Return live sessions, dropping registry files whose process has exited."""
    from coding_agent.resources.usage import process_alive

    records: list[ActiveSession] = []
    for path in sorted(active_dir().glob("*.json")):
        record = _load(path)
        if record is None:
            continue
        if process_alive(record.pid):
            records.append(record)
            continue
        if include_dead:
            records.append(record)
            continue
        try:
            path.unlink()
        except OSError:
            pass
    return records


def active_session_ids() -> set[str]:
    """Session ids currently owned by a live Symphony process."""
    return {record.session_id for record in list_active()}
