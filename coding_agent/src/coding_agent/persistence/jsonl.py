"""JSONL persistence for coding-agent sessions.

One append-only file per session under ``.symphony/sessions/<session_id>.jsonl``.
Conversation saves append new messages when history only grows; compaction or
other rewrites replace the message entries and keep events, spawns, and
checkpoints. Token deltas are not stored.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from core_ai.types import Message
from core_harness import Checkpoint

_SESSION_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_SKIP_EVENTS = frozenset({"text_delta", "reasoning_delta", "tool_call_delta"})
_MESSAGE_FIELDS = ("role", "content", "tool_calls", "tool_call_id", "tool_call_metadata")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sessions_dir(workspace: Union[str, Path]) -> Path:
    """Default session directory for a workspace."""
    return Path(workspace).expanduser().resolve() / ".symphony" / "sessions"


@dataclass(frozen=True)
class SessionSummary:
    """Small displayable summary of a persisted session."""

    session_id: str
    updated_at: str


class JsonlPersistence:
    """Append-only JSONL store for harness conversations, checkpoints, and journal."""

    def __init__(self, root: Union[str, Path]) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._event_keys: Dict[str, set[tuple[str, int]]] = {}

    def _path(self, session_id: str) -> Path:
        if not _SESSION_ID.match(session_id):
            raise ValueError(f"invalid session_id: {session_id!r}")
        return self.root / f"{session_id}.jsonl"

    def _read_entries(self, session_id: str) -> List[Dict[str, Any]]:
        path = self._path(session_id)
        if not path.is_file():
            return []
        entries: List[Dict[str, Any]] = []
        with path.open(encoding="utf-8") as handle:
            for raw in handle:
                line = raw.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    entries.append(item)
        return entries

    def _append_entries(self, session_id: str, entries: List[Dict[str, Any]]) -> None:
        if not entries:
            return
        path = self._path(session_id)
        with path.open("a", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _write_entries(self, session_id: str, entries: List[Dict[str, Any]]) -> None:
        path = self._path(session_id)
        tmp = path.with_name(path.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        tmp.replace(path)

    def _header(self, session_id: str) -> Dict[str, Any]:
        return {"type": "header", "session_id": session_id, "created_at": _utc_now()}

    def _message_entry(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"type": "message", **payload}

    def _message_payload(self, message: Message) -> Dict[str, Any]:
        return message.model_dump()

    def _messages_from(self, entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        dumped: List[Dict[str, Any]] = []
        for entry in entries:
            if entry.get("type") != "message":
                continue
            dumped.append({field: entry.get(field) for field in _MESSAGE_FIELDS})
        return dumped

    def _remember_event_keys(self, session_id: str, entries: List[Dict[str, Any]]) -> set[tuple[str, int]]:
        keys = self._event_keys.setdefault(session_id, set())
        for entry in entries:
            if entry.get("type") != "event":
                continue
            payload = entry.get("payload") or {}
            run_id = payload.get("run_id")
            seq = payload.get("seq")
            if run_id and isinstance(seq, int):
                keys.add((str(run_id), seq))
        return keys

    def flush_events(self) -> None:
        """No-op. Lifecycle events are appended immediately."""
        return None

    async def append_event(self, *, event_type: str, payload: dict[str, Any]) -> None:
        if event_type in _SKIP_EVENTS:
            return
        session_id = str(payload.get("session_id") or "")
        if not session_id:
            return
        with self._lock:
            entries = self._read_entries(session_id)
            keys = self._remember_event_keys(session_id, entries)
            run_id = payload.get("run_id")
            seq = payload.get("seq")
            if run_id and isinstance(seq, int) and (str(run_id), seq) in keys:
                return
            outgoing: List[Dict[str, Any]] = []
            if not entries:
                outgoing.append(self._header(session_id))
            outgoing.append(
                {
                    "type": "event",
                    "event_type": event_type,
                    "payload": dict(payload),
                }
            )
            if event_type == "agent_spawned":
                outgoing.append(
                    {
                        "type": "spawn",
                        "child_id": payload.get("child_id"),
                        "parent_id": payload.get("parent_id") or payload.get("agent_id"),
                        "parent_session_id": payload.get("session_id"),
                        "session_id": payload.get("child_session_id"),
                        "status": "running",
                        "output_text": "",
                        "metadata": dict(payload),
                    }
                )
            elif event_type in {"agent_completed", "agent_failed"}:
                status = "completed" if event_type == "agent_completed" else (
                    "cancelled" if payload.get("error_type") == "HarnessCancelled" else "failed"
                )
                outgoing.append(
                    {
                        "type": "spawn_status",
                        "child_id": payload.get("child_id"),
                        "status": status,
                        "output_text": payload.get("output_text") or payload.get("message") or "",
                    }
                )
            self._append_entries(session_id, outgoing)
            if run_id and isinstance(seq, int):
                keys.add((str(run_id), seq))

    async def load_events(self, *, session_id: str) -> list[tuple[str, dict[str, Any]]]:
        with self._lock:
            entries = self._read_entries(session_id)
        events: list[tuple[str, dict[str, Any]]] = []
        for entry in entries:
            if entry.get("type") != "event":
                continue
            event_type = str(entry.get("event_type") or "")
            payload = entry.get("payload")
            if event_type and isinstance(payload, dict):
                events.append((event_type, dict(payload)))
        return events

    async def load_children(self, *, parent_session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            entries = self._read_entries(parent_session_id)
        children: Dict[str, dict[str, Any]] = {}
        order: List[str] = []
        for entry in entries:
            kind = entry.get("type")
            if kind == "spawn":
                child_id = str(entry.get("child_id") or "")
                if not child_id:
                    continue
                metadata = dict(entry.get("metadata") or {})
                children[child_id] = {
                    **metadata,
                    "status": str(entry.get("status") or "running"),
                    "output_text": str(entry.get("output_text") or ""),
                }
                if child_id not in order:
                    order.append(child_id)
            elif kind == "spawn_status":
                child_id = str(entry.get("child_id") or "")
                if child_id not in children:
                    continue
                children[child_id]["status"] = str(entry.get("status") or children[child_id]["status"])
                children[child_id]["output_text"] = str(
                    entry.get("output_text") or children[child_id].get("output_text") or ""
                )
        return [children[child_id] for child_id in order]

    async def save_conversation(
        self,
        *,
        session_id: str,
        messages: List[Message],
    ) -> None:
        incoming = [self._message_payload(message) for message in messages]
        with self._lock:
            entries = self._read_entries(session_id)
            stored = self._messages_from(entries)
            if not entries:
                self._append_entries(
                    session_id,
                    [self._header(session_id), *[self._message_entry(item) for item in incoming]],
                )
                return
            if stored == incoming[: len(stored)] and len(incoming) >= len(stored):
                extra = incoming[len(stored) :]
                if extra:
                    self._append_entries(
                        session_id,
                        [self._message_entry(item) for item in extra],
                    )
                return
            header = next(
                (entry for entry in entries if entry.get("type") == "header"),
                self._header(session_id),
            )
            others = [
                entry
                for entry in entries
                if entry.get("type") not in {"header", "message"}
            ]
            self._write_entries(
                session_id,
                [header, *[self._message_entry(item) for item in incoming], *others],
            )
            self._event_keys.pop(session_id, None)

    async def load_conversation(self, *, session_id: str) -> List[Message]:
        with self._lock:
            entries = self._read_entries(session_id)
        messages: List[Message] = []
        for entry in entries:
            if entry.get("type") != "message":
                continue
            payload = {field: entry.get(field) for field in _MESSAGE_FIELDS}
            messages.append(Message.model_validate(payload))
        return messages

    async def list_sessions(self) -> List[SessionSummary]:
        """List parent sessions, newest first. Child session files are omitted."""
        with self._lock:
            child_ids: set[str] = set()
            summaries: List[tuple[float, SessionSummary]] = []
            for path in self.root.glob("*.jsonl"):
                if path.name.endswith(".jsonl.tmp"):
                    continue
                session_id = path.stem
                if not _SESSION_ID.match(session_id):
                    continue
                entries = self._read_entries(session_id)
                for entry in entries:
                    if entry.get("type") != "spawn":
                        continue
                    child_session = str(entry.get("session_id") or "")
                    if child_session:
                        child_ids.add(child_session)
                updated = datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                ).isoformat()
                summaries.append(
                    (path.stat().st_mtime, SessionSummary(session_id=session_id, updated_at=updated))
                )
        return [
            summary
            for _, summary in sorted(summaries, key=lambda item: item[0], reverse=True)
            if summary.session_id not in child_ids
        ]

    async def save_checkpoint(self, *, checkpoint: Checkpoint) -> None:
        payload = checkpoint.model_dump()
        payload.pop("messages", None)
        with self._lock:
            entries = self._read_entries(checkpoint.session_id)
            outgoing: List[Dict[str, Any]] = []
            if not entries:
                outgoing.append(self._header(checkpoint.session_id))
            outgoing.append({"type": "checkpoint", **payload})
            self._append_entries(checkpoint.session_id, outgoing)

    async def load_checkpoint(self, *, session_id: str) -> Optional[Checkpoint]:
        with self._lock:
            entries = self._read_entries(session_id)
        latest: Optional[Dict[str, Any]] = None
        for entry in entries:
            if entry.get("type") == "checkpoint":
                latest = entry
        if latest is None:
            return None
        payload = {key: value for key, value in latest.items() if key != "type"}
        payload.setdefault("session_id", session_id)
        payload["messages"] = [
            Message.model_validate({field: entry.get(field) for field in _MESSAGE_FIELDS})
            for entry in entries
            if entry.get("type") == "message"
        ]
        return Checkpoint.model_validate(payload)
