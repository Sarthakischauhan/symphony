"""JSONL persistence for coding-agent sessions.

One append-only file per session under ``.sessions/<session_id>.jsonl``.
The transcript is the source of truth: conversation messages are stored as
typed events and compaction stores a snapshot event. Runtime context is
reconstructed from those events; no separate context file is written.
"""

from __future__ import annotations

import json
import re
import shutil
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from core_ai.content import text_from_content
from core_ai.types import Message
from core_harness import Checkpoint
from core_harness.context import COMPACTED_CONTEXT_MARK

_SESSION_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_SKIP_EVENTS = frozenset({"text_delta", "reasoning_delta", "tool_call_delta"})
_MESSAGE_FIELDS = ("role", "content", "tool_calls", "tool_call_id", "tool_call_metadata")
_MESSAGE_TYPES = frozenset({"system", "user", "assistant", "tool_result"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sessions_dir(workspace: Union[str, Path] | None = None) -> Path:
    """Return the global Symphony session directory, migrating old sessions.

    Older releases stored sessions in ``<workspace>/.sessions``. On first use,
    move those files into the global directory. Migration is deliberately
    file-by-file and only removes the legacy directory after every move has
    succeeded, so an interrupted migration remains resumable.
    """
    target = (Path.home() / ".symphony" / "sessions").expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    if workspace is not None:
        legacy = Path(workspace).expanduser().resolve() / ".sessions"
        if legacy.is_dir() and legacy != target:
            try:
                for source in legacy.iterdir():
                    destination = target / source.name
                    if source.is_file() and not destination.exists():
                        shutil.move(str(source), str(destination))
                if not any(legacy.iterdir()):
                    legacy.rmdir()
            except OSError:
                # Leave the legacy directory in place; resume can retry later.
                pass
    return target


@dataclass(frozen=True)
class SessionSummary:
    """Small displayable summary of a persisted session."""

    session_id: str
    updated_at: str
    message_count: int = 0
    first_message: str = ""


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

    def _next_seq(self, entries: List[Dict[str, Any]]) -> int:
        return max((int(entry.get("seq", 0)) for entry in entries if str(entry.get("seq", "0")).isdigit()), default=0) + 1

    def _header(self, session_id: str) -> Dict[str, Any]:
        return {"type": "header", "session_id": session_id, "seq": 1, "created_at": _utc_now()}

    def _message_entry(self, payload: Dict[str, Any], *, seq: int) -> Dict[str, Any]:
        role = str(payload.get("role") or "message")
        event_type = "tool_result" if role == "tool" else role
        return {"type": "message", "event_type": event_type, "seq": seq, "message": payload, **payload}

    def _message_payload_from_entry(self, entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if entry.get("type") == "message":  # legacy JSONL
            return {field: entry.get(field) for field in _MESSAGE_FIELDS}
        if entry.get("type") in {"system", "user", "assistant", "tool_result"}:
            return {field: entry.get(field) for field in _MESSAGE_FIELDS}
        payload = entry.get("message")
        if isinstance(payload, dict):
            return {field: payload.get(field) for field in _MESSAGE_FIELDS}
        return None

    def _message_payload(self, message: Message) -> Dict[str, Any]:
        return message.model_dump()

    def _messages_from(self, entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Build the model context; never use this for rendering history."""
        dumped: List[Dict[str, Any]] = []
        latest = next(
            (
                entry
                for entry in reversed(entries)
                if entry.get("type") in {"compaction", "compacted"}
            ),
            None,
        )
        if latest is None:
            return [payload for entry in entries
                    if (payload := self._message_payload_from_entry(entry)) is not None]

        system = latest.get("system")
        if not isinstance(system, dict):
            system = next((entry.get("message") for entry in entries
                           if entry.get("type") == "message"
                           and entry.get("message", {}).get("role") == "system"), None)
        if isinstance(system, dict):
            dumped.append(dict(system))
        summary = latest.get("summary")
        if isinstance(summary, dict):
            dumped.append(dict(summary))
        elif isinstance(summary, str) and summary:
            dumped.append({
                "role": str(latest.get("summary_role") or "user"),
                "content": summary,
            })
        through = int(latest.get("through_seq", 0) or 0)
        for entry in entries:
            try:
                seq = int(entry.get("seq", 0))
            except (TypeError, ValueError):
                seq = 0
            if seq <= through:
                continue
            payload = self._message_payload_from_entry(entry)
            if payload is not None:
                dumped.append(payload)
        return dumped

    def _transcript_messages(self, entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Return every persisted message, including messages before compaction."""
        return [payload for entry in entries
                if (payload := self._message_payload_from_entry(entry)) is not None]

    def _remember_event_keys(self, session_id: str, entries: List[Dict[str, Any]]) -> set[tuple[str, int]]:
        keys = self._event_keys.setdefault(session_id, set())
        for entry in entries:
            if not entry.get("event_type"):
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
                    "type": event_type,
                    "event_type": event_type,
                    "seq": seq if isinstance(seq, int) else self._next_seq(entries),
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
            if not entry.get("event_type") or entry.get("type") == "message":
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
                header = self._header(session_id)
                self._append_entries(
                    session_id,
                    [header, *[
                        self._message_entry(item, seq=header["seq"] + index)
                        for index, item in enumerate(incoming, 1)
                    ]],
                )
                return
            if stored == incoming[: len(stored)] and len(incoming) >= len(stored):
                extra = incoming[len(stored) :]
                if extra:
                    next_seq = self._next_seq(entries)
                    self._append_entries(
                        session_id,
                        [self._message_entry(item, seq=next_seq + index) for index, item in enumerate(extra)],
                    )
                return
            # A rewrite means the harness compacted its runtime context. Keep
            # the complete transcript and append only a checkpoint plus the
            # retained suffix; compaction must never erase TUI history.
            previous_seq = max(
                (int(entry.get("seq", 0)) for entry in entries
                 if str(entry.get("seq", "0")).isdigit()), default=0
            )
            candidates = list(incoming)
            system = next((item for item in candidates if item.get("role") == "system"), None)
            if system is not None:
                candidates.remove(system)
            summary = candidates.pop(0) if candidates else {"role": "user", "content": ""}
            next_seq = self._next_seq(entries)
            boundary = {
                "type": "compaction",
                "seq": next_seq,
                "through_seq": previous_seq,
                "summary": summary,
                "summary_role": str(summary.get("role") or "user"),
                "system": system,
                "created_at": _utc_now(),
            }
            additions = [
                self._message_entry(item, seq=next_seq + index)
                for index, item in enumerate(candidates, 1)
            ]
            self._append_entries(session_id, [boundary, *additions])
            self._event_keys.pop(session_id, None)

    async def load_conversation(self, *, session_id: str) -> List[Message]:
        """Load the reconstructed model context (runtime view)."""
        with self._lock:
            entries = self._read_entries(session_id)
        return [Message.model_validate(payload) for payload in self._messages_from(entries)]

    async def load_transcript(self, *, session_id: str) -> List[Message]:
        """Load the complete persisted transcript for the TUI/history view."""
        with self._lock:
            entries = self._read_entries(session_id)
        return [Message.model_validate(payload) for payload in self._transcript_messages(entries)]

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
                # The picker only needs file metadata and the first user
                # message. Do not decode every JSON object in large transcripts.
                first_message = ""
                message_count = 0
                with path.open(encoding="utf-8") as handle:
                    for raw in handle:
                        if not raw.strip():
                            continue
                        try:
                            entry = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(entry, dict):
                            continue
                        if entry.get("type") == "spawn":
                            child_session = str(entry.get("session_id") or "")
                            if child_session:
                                child_ids.add(child_session)
                        if entry.get("type") not in _MESSAGE_TYPES:
                            continue
                        message_count += 1
                        if first_message:
                            continue
                        content = entry.get("content")
                        if entry.get("type") == "tool_result":
                            content = entry.get("message", {}).get("content")
                        text = text_from_content(content).strip()
                        if entry.get("type") == "user" and text and not text.startswith(COMPACTED_CONTEXT_MARK):
                            first_message = text
                updated = datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                ).isoformat()
                summaries.append(
                    (
                        path.stat().st_mtime,
                        SessionSummary(
                            session_id=session_id,
                            updated_at=updated,
                            message_count=message_count,
                            first_message=first_message,
                        ),
                    )
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
            Message.model_validate(message) for message in self._messages_from(entries)
        ]
        return Checkpoint.model_validate(payload)
