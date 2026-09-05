"""SQLite persistence for coding-agent sessions (messages + checkpoints)."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Union

from core_ai.types import Message
from core_harness import Checkpoint


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SessionSummary:
    """Small displayable summary of a persisted session."""

    session_id: str
    updated_at: str


class SqlitePersistence:
    """stdlib sqlite3 store for harness conversations and checkpoints."""

    def __init__(self, db_path: Union[str, Path]) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._pending_events: list[tuple[str, dict[str, Any]]] = []
        self._last_flush = time.monotonic()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    session_id TEXT PRIMARY KEY,
                    messages_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS checkpoints (
                    session_id TEXT NOT NULL,
                    turn INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (session_id, turn)
                );
                CREATE TABLE IF NOT EXISTS session_updates (
                    ordinal INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(run_id, seq)
                );
                CREATE INDEX IF NOT EXISTS updates_by_session ON session_updates(session_id, ordinal);
                CREATE TABLE IF NOT EXISTS child_sessions (
                    child_id TEXT PRIMARY KEY,
                    parent_id TEXT NOT NULL,
                    parent_session_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    output_text TEXT NOT NULL DEFAULT ''
                );
                """
            )

    async def append_event(self, *, event_type: str, payload: dict[str, Any]) -> None:
        """Optional harness journal. Batch token deltas; flush lifecycle boundaries."""
        self._pending_events.append((event_type, dict(payload)))
        if (event_type not in {"text_delta", "reasoning_delta", "tool_call_delta"}
                or len(self._pending_events) >= 64
                or time.monotonic() - self._last_flush >= 0.25):
            self.flush_events()

    def flush_events(self) -> None:
        if not self._pending_events:
            return
        with self._connect() as connection:
            for event_type, payload in self._pending_events:
                connection.execute(
                    "INSERT OR IGNORE INTO session_updates "
                    "(session_id, run_id, seq, event_type, payload_json) VALUES (?, ?, ?, ?, ?)",
                    (payload["session_id"], payload["run_id"], payload["seq"],
                     event_type, json.dumps(payload)),
                )
                if event_type == "agent_spawned":
                    connection.execute(
                        "INSERT INTO child_sessions "
                        "(child_id, parent_id, parent_session_id, session_id, metadata_json, status) "
                        "VALUES (?, ?, ?, ?, ?, 'running') ON CONFLICT(child_id) DO NOTHING",
                        (payload["child_id"], payload["agent_id"], payload["session_id"],
                         payload["child_session_id"], json.dumps(payload)),
                    )
                elif event_type in {"agent_completed", "agent_failed"}:
                    status = "completed" if event_type == "agent_completed" else (
                        "cancelled" if payload.get("error_type") == "HarnessCancelled" else "failed"
                    )
                    connection.execute(
                        "UPDATE child_sessions SET status = ?, output_text = ? WHERE child_id = ?",
                        (status, payload.get("output_text") or payload.get("message") or "", payload["child_id"]),
                    )
        self._pending_events.clear()
        self._last_flush = time.monotonic()

    async def load_events(self, *, session_id: str) -> list[tuple[str, dict[str, Any]]]:
        self.flush_events()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT event_type, payload_json FROM session_updates WHERE session_id = ? ORDER BY ordinal",
                (session_id,),
            ).fetchall()
        return [(row["event_type"], json.loads(row["payload_json"])) for row in rows]

    async def load_children(self, *, parent_session_id: str) -> list[dict[str, Any]]:
        self.flush_events()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM child_sessions WHERE parent_session_id = ? ORDER BY rowid",
                (parent_session_id,),
            ).fetchall()
        return [{**json.loads(row["metadata_json"]), "status": row["status"],
                 "output_text": row["output_text"]} for row in rows]

    async def save_conversation(
        self,
        *,
        session_id: str,
        messages: List[Message],
    ) -> None:
        payload = json.dumps([message.model_dump() for message in messages])
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO conversations (session_id, messages_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    messages_json = excluded.messages_json,
                    updated_at = excluded.updated_at
                """,
                (session_id, payload, _utc_now()),
            )

    async def load_conversation(self, *, session_id: str) -> List[Message]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT messages_json FROM conversations WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return []
        raw = json.loads(row["messages_json"])
        return [Message.model_validate(item) for item in raw]

    async def list_sessions(self) -> List[SessionSummary]:
        """List persisted sessions, newest first."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT session_id, updated_at
                FROM conversations
                WHERE session_id NOT IN (SELECT session_id FROM child_sessions)
                ORDER BY updated_at DESC
                """
            ).fetchall()
        return [
            SessionSummary(session_id=row["session_id"], updated_at=row["updated_at"])
            for row in rows
        ]

    async def save_checkpoint(self, *, checkpoint: Checkpoint) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO checkpoints (
                    session_id, turn, status, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id, turn) DO UPDATE SET
                    status = excluded.status,
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (
                    checkpoint.session_id,
                    checkpoint.turn,
                    checkpoint.status,
                    checkpoint.model_dump_json(),
                    _utc_now(),
                ),
            )

    async def load_checkpoint(self, *, session_id: str) -> Optional[Checkpoint]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM checkpoints
                WHERE session_id = ?
                ORDER BY turn DESC, created_at DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return Checkpoint.model_validate_json(row["payload_json"])
