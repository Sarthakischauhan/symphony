"""JSONL persistence for coding-agent sessions.

One append-only transcript per session under ``<root>/<session_id>/transcript.jsonl``.
The transcript is the source of truth: conversation messages are stored as
typed events and compaction stores a snapshot event. Runtime context is
reconstructed from those events; no separate context file is written.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Union

from coding_agent.addons.persistence.artifacts import append_bytes, publish, safe_path, snapshot
from coding_agent.addons.persistence.images import archive, hydrate
from core_ai.content import text_from_content
from core_ai.types import Message
from core_harness import Checkpoint
from core_harness.context import COMPACTED_CONTEXT_MARK
from coding_agent.addons.persistence.collection import (
    TERMINAL_EVENT_TYPES,
    apply_collection,
    collectable_from_events,
    collected_keys,
)

_SESSION_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_SKIP_EVENTS = frozenset({"text_delta", "reasoning_delta", "tool_call_delta"})
_MESSAGE_FIELDS = ("role", "content", "tool_calls", "tool_call_id", "tool_call_metadata")
_MESSAGE_TYPES = frozenset({"system", "user", "assistant", "tool_result", "message"})


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
        if legacy.is_dir() and not legacy.is_symlink() and legacy != target:
            try:
                for source in legacy.iterdir():
                    destination = target / source.name
                    if source.is_file() and not source.is_symlink() and not destination.exists() and not destination.is_symlink():
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
    client: str = ""


class JsonlPersistence:
    """Append-only JSONL store for harness conversations, checkpoints, and journal."""

    def __init__(self, root: Union[str, Path]) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._event_keys: Dict[str, set[tuple[str, int]]] = {}
        self._entries: Dict[str, List[Dict[str, Any]]] = {}
        self._marks: Dict[str, int] = {}
        self._held: Dict[str, list[int]] = {}
        # Product fields (goal, todo, live background jobs) merged into every
        # checkpoint so an interrupted run can be continued later.
        self.checkpoint_metadata: Callable[[], Dict[str, Any]] = dict

    def session_dir(self, session_id: str) -> Path:
        """Return a validated session artifact directory (without creating it)."""
        if session_id in {".", ".."} or not _SESSION_ID.fullmatch(session_id):
            raise ValueError(f"invalid session_id: {session_id!r}")
        return safe_path(self.root, session_id)

    def _path(self, session_id: str) -> Path:
        return safe_path(self.session_dir(session_id), "transcript.jsonl")

    def _acquire_session(self, session_id: str) -> None:
        held = self._held.get(session_id)
        if held is not None:
            held[1] += 1
            return
        directory = self.session_dir(session_id)
        directory.mkdir(parents=True, exist_ok=True)
        lock_path = safe_path(directory, ".lock")
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
        except BaseException:
            os.close(fd)
            raise
        self._held[session_id] = [fd, 1]

    def _release_session(self, session_id: str) -> None:
        held = self._held[session_id]
        held[1] -= 1
        if held[1] == 0:
            fd = held[0]
            del self._held[session_id]
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    @contextmanager
    def _session_lock(self, session_id: str) -> Iterator[None]:
        """Exclusive cross-process lock for migrate and append."""
        self._acquire_session(session_id)
        try:
            yield
        finally:
            self._release_session(session_id)

    def _metadata_path(self, session_id: str) -> Path:
        return safe_path(self.session_dir(session_id), "metadata.json")

    def _read_metadata(self, session_id: str) -> Optional[Dict[str, Any]]:
        path = self._metadata_path(session_id)
        if not path.exists():
            return None
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"session bundle metadata unreadable: {session_id}") from exc
        if not isinstance(saved, dict):
            raise ValueError(f"session bundle metadata unreadable: {session_id}")
        return saved

    def _require_version(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Refuse a bundle whose version is missing or not 1."""
        meta = self._read_metadata(session_id)
        transcript = self._path(session_id)
        has_body = transcript.is_file() and not transcript.is_symlink() and transcript.stat().st_size > 0
        if meta is None:
            if has_body:
                raise ValueError(f"session bundle version missing: {session_id}")
            return None
        if meta.get("version") != 1:
            raise ValueError(f"unsupported session bundle version: {meta.get('version')!r}")
        return meta

    def _write_metadata(self, session_id: str, metadata: Dict[str, Any]) -> None:
        snapshot(self._metadata_path(session_id), {**metadata, "version": 1, "session_id": session_id})

    def _ensure_metadata(self, session_id: str) -> Dict[str, Any]:
        meta = self._require_version(session_id)
        if meta is not None:
            return meta
        created = _utc_now()
        meta = {
            "version": 1,
            "session_id": session_id,
            "created_at": created,
            "updated_at": created,
            "client": getattr(self, "client", "") or "",
        }
        self._write_metadata(session_id, meta)
        return meta

    def _legacy_path(self, session_id: str) -> Path:
        return safe_path(self.root, f"{session_id}.jsonl")

    def _mark(self, path: Path) -> int:
        if not path.is_file() or path.is_symlink():
            return -1
        return path.stat().st_size

    @staticmethod
    def _parse_legacy(raw: bytes) -> tuple[int, List[Dict[str, Any]]]:
        skipped = 0
        entries: List[Dict[str, Any]] = []
        for raw_line in raw.decode("utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            if isinstance(item, dict):
                entries.append(item)
            else:
                skipped += 1
        return skipped, entries

    @staticmethod
    def _strip_imported_jobs(entry: Dict[str, Any]) -> Dict[str, Any]:
        """Drop background job pids that arrived in an unvalidated legacy file."""
        if entry.get("type") != "checkpoint":
            return entry
        metadata = entry.get("metadata")
        if not isinstance(metadata, dict) or "background_jobs" not in metadata:
            return entry
        return {**entry, "metadata": {key: value for key, value in metadata.items() if key != "background_jobs"}}

    def _quarantine_legacy(self, session_id: str, raw: bytes, skipped: int) -> None:
        digest = hashlib.sha256(raw).hexdigest()
        dest = safe_path(self.session_dir(session_id), "quarantine", f"{digest}.jsonl")
        if not dest.is_file():
            publish(dest, raw)
        meta = self._read_metadata(session_id) or {
            "version": 1, "session_id": session_id, "created_at": _utc_now(),
        }
        meta["quarantine"] = {"sha256": digest, "skipped_lines": skipped, "bytes": len(raw)}
        self._write_metadata(session_id, meta)

    def _remember_legacy(self, session_id: str, raw: bytes) -> None:
        meta = self._ensure_metadata(session_id)
        meta["legacy_import"] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        self._write_metadata(session_id, meta)

    @staticmethod
    def _entry_key(entry: Dict[str, Any]) -> tuple[Any, ...]:
        seq = entry.get("seq")
        if isinstance(seq, int) and not isinstance(seq, bool):
            return ("seq", entry.get("type"), seq)
        return ("json", json.dumps(entry, sort_keys=True, ensure_ascii=False))

    def _encode(self, entries: List[Dict[str, Any]]) -> bytes:
        return "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in entries).encode("utf-8")

    def _publish_transcript(self, session_id: str, entries: List[Dict[str, Any]]) -> None:
        """Publish a transcript only while it is still empty. Never replace appended bytes."""
        path = self._path(session_id)
        if path.is_symlink():
            raise ValueError(f"unsafe artifact symlink: {path}")
        if path.is_file() and path.stat().st_size > 0:
            return
        self._ensure_metadata(session_id)
        publish(path, self._encode(entries))
        self._entries.pop(session_id, None)
        self._marks.pop(session_id, None)

    def _sync_legacy(self, session_id: str) -> None:
        """Fold a newer flat JSONL into the bundle. Do not replace an appended transcript."""
        legacy = self._legacy_path(session_id)
        if not legacy.exists():
            return
        if legacy.is_symlink() or not legacy.is_file():
            return
        raw = legacy.read_bytes()
        path = self._path(session_id)
        transcript_size = path.stat().st_size if path.is_file() and not path.is_symlink() else 0
        meta = self._read_metadata(session_id)
        if transcript_size > 0:
            if meta is None or meta.get("version") != 1:
                raise ValueError(
                    f"session bundle version missing: {session_id}" if meta is None
                    else f"unsupported session bundle version: {meta.get('version')!r}"
                )
        recorded = meta.get("legacy_import") if isinstance(meta, dict) else None
        if not isinstance(recorded, dict) or not isinstance(recorded.get("bytes"), int):
            if transcript_size <= 0:
                self._import_legacy_bytes(session_id, raw, raw)
            elif legacy.stat().st_mtime > path.stat().st_mtime:
                self._import_legacy_bytes(session_id, raw, raw, only_missing=True)
            else:
                self._remember_legacy(session_id, raw)
            return
        cursor = recorded["bytes"]
        if cursor < 0 or cursor > len(raw):
            self._note_rejected_legacy(session_id, raw)
            return
        prefix = raw[:cursor]
        if hashlib.sha256(prefix).hexdigest() != recorded.get("sha256"):
            self._note_rejected_legacy(session_id, raw)
            return
        if len(raw) == cursor:
            return
        self._import_legacy_bytes(session_id, raw, raw[cursor:])

    def _note_rejected_legacy(self, session_id: str, raw: bytes) -> None:
        skipped, _entries = self._parse_legacy(raw)
        if skipped:
            self._quarantine_legacy(session_id, raw, skipped)
        digest = hashlib.sha256(raw).hexdigest()
        meta = self._ensure_metadata(session_id)
        legacy_import = dict(meta.get("legacy_import") or {})
        legacy_import["rejected_sha256"] = digest
        meta["legacy_import"] = legacy_import
        self._write_metadata(session_id, meta)

    def _import_legacy_bytes(
        self, session_id: str, raw: bytes, chunk: bytes, *, only_missing: bool = False
    ) -> None:
        skipped, entries = self._parse_legacy(chunk)
        if skipped:
            self._quarantine_legacy(session_id, raw, skipped)
            entries = [self._strip_imported_jobs(entry) for entry in entries]
        entries = archive(entries, self.session_dir(session_id))
        path = self._path(session_id)
        transcript_size = path.stat().st_size if path.is_file() and not path.is_symlink() else 0
        if transcript_size <= 0 and not only_missing:
            self._publish_transcript(session_id, entries)
        elif entries:
            if only_missing:
                existing = {self._entry_key(entry) for entry in self._load_transcript(path)}
                entries = [entry for entry in entries if self._entry_key(entry) not in existing]
            if entries:
                self._append_entries(session_id, entries)
        self._remember_legacy(session_id, raw)

    def _load_transcript(self, path: Path) -> List[Dict[str, Any]]:
        if not path.is_file() or path.is_symlink():
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

    def _artifacts(
        self, session_id: str, entries: List[Dict[str, Any]], *, updated: bool = True
    ) -> None:
        metadata = self._require_version(session_id) or {}
        directory = self.session_dir(session_id)
        created = next((item.get("created_at") for item in entries
                        if item.get("type") == "header"), None) or _utc_now()
        self._write_metadata(session_id, {
            **metadata, "version": 1, "session_id": session_id,
            "created_at": metadata.get("created_at") or created,
            "updated_at": _utc_now() if updated else metadata.get("updated_at", created),
        })
        for entry in entries:
            if entry.get("type") in {"compaction", "compacted"}:
                seq = entry.get("seq", 0)
                if isinstance(seq, bool) or not isinstance(seq, int):
                    continue
                snapshot(safe_path(directory, "compactions", f"{seq}.json"), {**entry, "version": 1})
            elif entry.get("type") == "checkpoint":
                snapshot(safe_path(directory, "checkpoint.json"),
                         {key: value for key, value in {**entry, "version": 1}.items()
                          if key != "messages"})

    def _read_entries(self, session_id: str) -> List[Dict[str, Any]]:
        with self._session_lock(session_id):
            self._sync_legacy(session_id)
            self._require_version(session_id)
            path = self._path(session_id)
            mark = self._mark(path)
            entries = self._load_transcript(path) if mark >= 0 else []
            if mark >= 0:
                self._artifacts(session_id, entries, updated=False)
            self._entries[session_id] = entries
            self._marks[session_id] = mark
            return entries

    def _cached_entries(self, session_id: str) -> List[Dict[str, Any]]:
        """Return the journal without reading it when its cached size is current."""
        path = self._path(session_id)
        mark = self._mark(path)
        if session_id in self._entries and self._marks.get(session_id) == mark:
            return self._entries[session_id]
        return self._read_entries(session_id)

    def _stamp_client(self, session_id: str) -> None:
        """Record the product once. A later client must not overwrite it."""
        client = getattr(self, "client", "") or ""
        if not client:
            return
        meta = self._ensure_metadata(session_id)
        if meta.get("client"):
            return
        self._write_metadata(session_id, {**meta, "client": client, "updated_at": _utc_now()})

    def _append_entries(self, session_id: str, entries: List[Dict[str, Any]]) -> None:
        if not entries:
            return
        with self._session_lock(session_id):
            self._stamp_client(session_id)
            self._ensure_metadata(session_id)
            path = self._path(session_id)
            mark = self._mark(path)
            if session_id not in self._entries or self._marks.get(session_id) != mark:
                self._entries[session_id] = self._load_transcript(path) if mark >= 0 else []
            entries = archive(entries, self.session_dir(session_id))
            append_bytes(path, self._encode(entries))
            self._entries[session_id].extend(entries)
            self._marks[session_id] = path.stat().st_size
            self._artifacts(session_id, entries)

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
        dumped = message.model_dump()
        return {field: dumped.get(field) for field in _MESSAGE_FIELDS}

    def _canonical_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {field: payload.get(field) for field in _MESSAGE_FIELDS}

    def _is_compact_mark(self, payload: Dict[str, Any]) -> bool:
        content = payload.get("content")
        text = content if isinstance(content, str) else text_from_content(content or "")
        return text.startswith(COMPACTED_CONTEXT_MARK)

    def _is_compact_rewrite(
        self,
        stored: List[Dict[str, Any]],
        incoming: List[Dict[str, Any]],
    ) -> bool:
        """True only when the runtime conversation actually dropped history."""
        if len(incoming) < len(stored):
            return True
        stored_marks = [item for item in stored if self._is_compact_mark(item)]
        incoming_marks = [item for item in incoming if self._is_compact_mark(item)]
        return bool(incoming_marks) and (
            not stored_marks or stored_marks[-1] != incoming_marks[-1]
        )

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
        with self._lock, self._session_lock(session_id):
            entries = self._cached_entries(session_id)
            if session_id not in self._event_keys:
                self._remember_event_keys(session_id, entries)
            keys = self._event_keys.setdefault(session_id, set())
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
            if event_type in TERMINAL_EVENT_TYPES:
                self._append_collection_overlays(
                    session_id,
                    self._entries.get(session_id, entries),
                    run_id=str(run_id) if run_id else None,
                )

    def _journal_events(
        self, entries: List[Dict[str, Any]]
    ) -> list[tuple[str, dict[str, Any]]]:
        events: list[tuple[str, dict[str, Any]]] = []
        for entry in entries:
            if not entry.get("event_type") or entry.get("type") == "message":
                continue
            event_type = str(entry.get("event_type") or "")
            payload = entry.get("payload")
            if event_type and isinstance(payload, dict):
                events.append((event_type, dict(payload)))
        return events

    async def collect_run_events(
        self,
        *,
        session_id: str,
        run_id: str | None = None,
        keys: Sequence[tuple[str, int]] | None = None,
    ) -> list[tuple[str, int]]:
        """Tag mid-run events as collected without rewriting historical lines.

        Appends one ``collected`` overlay per untagged event. The original
        journal entry stays as-is; ``load_events`` overlays ``collected: true``.
        """
        if not session_id:
            return []
        with self._lock, self._session_lock(session_id):
            entries = self._read_entries(session_id)
            return self._append_collection_overlays(
                session_id, entries, run_id=run_id, keys=keys
            )

    def _append_collection_overlays(
        self,
        session_id: str,
        entries: List[Dict[str, Any]],
        *,
        run_id: str | None = None,
        keys: Sequence[tuple[str, int]] | None = None,
    ) -> list[tuple[str, int]]:
        events = self._journal_events(entries)
        already = collected_keys(events)
        targets = list(keys) if keys is not None else collectable_from_events(
            events, run_id=run_id
        )
        pending = [key for key in targets if key not in already]
        if not pending:
            return []
        next_seq = self._next_seq(entries)
        overlays: List[Dict[str, Any]] = []
        for offset, (event_run_id, event_seq) in enumerate(pending):
            overlays.append(
                {
                    "type": "collected",
                    "event_type": "collected",
                    "seq": next_seq + offset,
                    "payload": {
                        "run_id": event_run_id,
                        "session_id": session_id,
                        "seq": event_seq,
                        "collected": True,
                    },
                }
            )
        self._append_entries(session_id, overlays)
        return pending

    async def annotate_run_completed(
        self,
        *,
        session_id: str,
        run_id: str,
        completion_verb: str,
        duration: str = "",
        elapsed_seconds: float | None = None,
    ) -> None:
        """Persist completed-run display fields without rewriting journal lines."""
        if not session_id or not run_id or not completion_verb:
            return
        payload: dict[str, Any] = {
            "session_id": session_id,
            "run_id": run_id,
            "completion_verb": completion_verb,
        }
        if duration:
            payload["duration"] = duration
        if elapsed_seconds is not None:
            payload["elapsed_seconds"] = elapsed_seconds
        await self.append_event(event_type="run_completed_meta", payload=payload)

    async def load_events(self, *, session_id: str) -> list[tuple[str, dict[str, Any]]]:
        with self._lock:
            entries = self._cached_entries(session_id)
        return apply_collection([(kind, hydrate(payload, self.session_dir(session_id)))
                                 for kind, payload in self._journal_events(entries)])

    async def load_children(self, *, parent_session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            entries = self._cached_entries(parent_session_id)
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
        with self._lock, self._session_lock(session_id):
            self._stamp_client(session_id)
            entries = self._read_entries(session_id)
            incoming = archive([self._message_payload(message) for message in messages],
                               self.session_dir(session_id))
            stored = [self._canonical_payload(item) for item in self._messages_from(entries)]
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
            if not self._is_compact_rewrite(stored, incoming):
                # In-place edits (including legacy tool stubs or injected memory) must
                # not mint a compaction boundary. Re-emitting the whole
                # conversation after through_seq is what ballooned session
                # files to thousands of duplicate message lines.
                extra = incoming[len(stored) :] if len(incoming) > len(stored) else []
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
                "version": 1,
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

    async def load_conversation(self, *, session_id: str) -> List[Message]:
        """Load the reconstructed model context (runtime view)."""
        with self._lock:
            entries = self._cached_entries(session_id)
        return [Message.model_validate(hydrate(payload, self.session_dir(session_id))) for payload in self._messages_from(entries)]

    async def load_transcript(self, *, session_id: str) -> List[Message]:
        """Load the complete persisted transcript for the TUI/history view."""
        with self._lock:
            entries = self._cached_entries(session_id)
        return [Message.model_validate(hydrate(payload, self.session_dir(session_id))) for payload in self._transcript_messages(entries)]

    async def list_sessions(self) -> List[SessionSummary]:
        """List parent sessions, newest first. Child session files are omitted."""
        with self._lock:
            child_ids: set[str] = set()
            summaries: List[tuple[float, SessionSummary]] = []
            paths: Dict[str, Path] = {}
            for candidate in self.root.iterdir():
                if candidate.is_symlink():
                    continue
                if candidate.is_file() and candidate.name.endswith(".jsonl") and not candidate.name.endswith(".tmp"):
                    paths.setdefault(candidate.name[: -len(".jsonl")], candidate)
                elif candidate.is_dir():
                    transcript = candidate / "transcript.jsonl"
                    if transcript.is_file() and not transcript.is_symlink():
                        paths[candidate.name] = transcript
            for session_id, path in paths.items():
                if session_id in {".", ".."} or not _SESSION_ID.fullmatch(session_id):
                    continue
                if not path.is_file() or path.is_symlink():
                    continue
                try:
                    self.session_dir(session_id)
                    safe_path(self.root, str(path.relative_to(self.root)))
                except ValueError:
                    continue
                # The picker only needs file metadata and the first user
                # message. Do not decode every JSON object in large transcripts.
                first_message = ""
                message_count = 0
                client = ""
                try:
                    meta = self._read_metadata(session_id)
                except ValueError:
                    meta = None
                if isinstance(meta, dict):
                    client = str(meta.get("client") or "")
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
                        payload = self._message_payload_from_entry(entry)
                        if payload is None:
                            continue
                        message_count += 1
                        if first_message:
                            continue
                        text = text_from_content(payload.get("content")).strip()
                        if payload.get("role") == "user" and text and not text.startswith(COMPACTED_CONTEXT_MARK):
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
                            client=client,
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
        payload["metadata"] = {**self.checkpoint_metadata(), **payload["metadata"]}
        with self._lock, self._session_lock(checkpoint.session_id):
            entries = self._read_entries(checkpoint.session_id)
            outgoing: List[Dict[str, Any]] = []
            if not entries:
                outgoing.append(self._header(checkpoint.session_id))
            outgoing.append({"type": "checkpoint", "version": 1, **payload})
            self._append_entries(checkpoint.session_id, outgoing)

    def checkpoint_goal(self, session_id: str) -> str:
        """Return the latest saved goal without rebuilding the conversation."""
        with self._lock:
            entries = self._cached_entries(session_id)
        for entry in reversed(entries):
            if entry.get("type") != "checkpoint":
                continue
            metadata = entry.get("metadata")
            if isinstance(metadata, dict):
                return str(metadata.get("goal") or "")
        return ""

    async def load_checkpoint(self, *, session_id: str) -> Optional[Checkpoint]:
        with self._lock:
            entries = self._cached_entries(session_id)
        latest: Optional[Dict[str, Any]] = None
        for entry in entries:
            if entry.get("type") == "checkpoint":
                latest = entry
        if latest is None:
            return None
        payload = hydrate({key: value for key, value in latest.items() if key != "type"}, self.session_dir(session_id))
        payload.setdefault("session_id", session_id)
        payload["messages"] = [
            Message.model_validate(hydrate(message, self.session_dir(session_id))) for message in self._messages_from(entries)
        ]
        return Checkpoint.model_validate(payload)

    async def load_compactions(self, session_id: str) -> List[Dict[str, Any]]:
        """Return compaction boundaries in transcript order, with hydrated content."""
        with self._lock:
            entries = self._read_entries(session_id)
            return [hydrate(entry, self.session_dir(session_id)) for entry in entries
                    if entry.get("type") in {"compaction", "compacted"}]
