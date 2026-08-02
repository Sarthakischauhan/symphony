"""SQLite persistence for coding-agent sessions (messages + checkpoints)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Union

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
                """
            )

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
