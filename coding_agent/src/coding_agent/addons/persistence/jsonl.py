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
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Sequence, Union

from coding_agent.addons.persistence.artifacts import (
    append_bytes,
    publish,
    refresh_snapshot,
    safe_path,
    snapshot,
)
from coding_agent.addons.persistence.images import archive, hydrate
from core_ai.content import text_from_content
from core_ai.types import Message
from core_harness import Checkpoint
from core_harness.context import COMPACTED_CONTEXT_MARK
from coding_agent.addons.persistence.collection import (
    COLLECTABLE_EVENT_TYPES,
    TERMINAL_EVENT_TYPES,
    apply_collection,
    event_key,
    is_collected,
)

_SESSION_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_SKIP_EVENTS = frozenset({"text_delta", "reasoning_delta", "tool_call_delta"})
_MESSAGE_FIELDS = ("role", "content", "tool_calls", "tool_call_id", "tool_call_metadata")
_MESSAGE_TYPES = frozenset({"system", "user", "assistant", "tool_result", "message"})


def _move_client_sessions(source: Path, target: Path, client: str) -> None:
    """Move bundles already tagged for ``client`` into that product's directory.

    Untagged chats stay where they are. A TUI cannot tell an old Zeron chat
    from an old TUI chat once they share a folder, so only an explicit tag moves.
    """
    if not source.is_dir():
        return
    for bundle in source.iterdir():
        if not bundle.is_dir() or bundle.is_symlink():
            continue
        meta_path = bundle / "metadata.json"
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(meta, dict) or meta.get("client") != client:
            continue
        destination = target / bundle.name
        if destination.exists():
            continue
        shutil.move(str(bundle), str(destination))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sessions_dir(
    workspace: Union[str, Path] | None = None,
    *,
    client: str = "",
) -> Path:
    """Return the session directory for one product, migrating old sessions.

    The TUI keeps its own directory so resume cannot see Zeron chats. Other
    clients stay in the shared directory. Older releases stored sessions in
    ``<workspace>/.sessions``; those files move into the shared directory on
    first use. Migration is file-by-file and only removes the legacy directory
    after every move has succeeded, so an interrupted migration remains resumable.
    """
    root = (Path.home() / ".symphony").expanduser().resolve()
    if client == "tui":
        target = root / "tui" / "sessions"
        shared = root / "sessions"
        target.mkdir(parents=True, exist_ok=True)
        _move_client_sessions(shared, target, "tui")
        return target
    target = root / "sessions"
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


def _entry_seq(entry: Mapping[str, Any]) -> int:
    try:
        return int(entry.get("seq", 0) or 0)
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True)
class SessionSummary:
    """Small displayable summary of a persisted session."""

    session_id: str
    updated_at: str
    message_count: int = 0
    first_message: str = ""
    client: str = ""


class _SessionIndex:
    """Incremental view of one journal. Reads are O(1) or O(result)."""

    def __init__(self, directory: Path) -> None:
        # Archived images resolve against the session directory when a
        # message is validated, as the full loaders did before the index.
        self.directory = directory
        self.entries: List[Dict[str, Any]] = []
        self.size = -1
        self.high_seq = 0
        self.event_keys: set[tuple[str, int]] = set()
        self.collected: set[tuple[str, int]] = set()
        self.collectable: Dict[str, List[tuple[str, int]]] = {}
        self.run_started: set[str] = set()
        self.latest_terminal_run = ""
        self.messages: List[Dict[str, Any]] = []
        self.hydrated: List[Message] = []
        self.context: List[Dict[str, Any]] = []
        self.hydrated_context: List[Message] = []
        self.context_through = -1
        self.latest_compaction: Optional[Dict[str, Any]] = None
        self.compactions: List[Dict[str, Any]] = []
        self.latest_checkpoint: Optional[Dict[str, Any]] = None
        self.children: Dict[str, dict[str, Any]] = {}
        self.child_order: List[str] = []
        self.message_count = 0
        self.first_message = ""
        self.child_ids: set[str] = set()

    def reset(self, entries: List[Dict[str, Any]], size: int) -> None:
        fresh = _SessionIndex(self.directory)
        self.__dict__.update(fresh.__dict__)
        self.entries = entries
        self.size = size
        self._ingest(entries)

    def extend(self, entries: List[Dict[str, Any]], size: int) -> None:
        self.entries.extend(entries)
        self.size = size
        self._ingest(entries)

    def _ingest(self, entries: Sequence[Dict[str, Any]]) -> None:
        for entry in entries:
            seq = _entry_seq(entry)
            if seq > self.high_seq:
                self.high_seq = seq
            self._note_event(entry)
            self._note_message(entry, seq)
            self._note_compaction(entry)
            self._note_checkpoint(entry)
            self._note_child(entry)
            self._note_listing(entry)

    def _note_event(self, entry: Dict[str, Any]) -> None:
        event_type = str(entry.get("event_type") or "")
        if not event_type or entry.get("type") == "message":
            return
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            return
        key = event_key(payload)
        if key is not None:
            self.event_keys.add(key)
        if event_type == "collected" or is_collected(payload):
            if key is not None:
                self.collected.add(key)
            return
        run_id = str(payload.get("run_id") or "")
        if not run_id or key is None:
            return
        if event_type == "run_started":
            self.run_started.add(run_id)
            return
        if event_type in TERMINAL_EVENT_TYPES:
            self.latest_terminal_run = run_id
            return
        if run_id in self.run_started and event_type in COLLECTABLE_EVENT_TYPES:
            bucket = self.collectable.setdefault(run_id, [])
            if key not in self.collected and key not in set(bucket):
                bucket.append(key)

    def _note_message(self, entry: Dict[str, Any], seq: int) -> None:
        payload = JsonlPersistence._message_payload_from_entry(entry)
        if payload is None:
            return
        self.messages.append(payload)
        self.hydrated.append(Message.model_validate(hydrate(payload, self.directory)))
        if self.latest_compaction is None or seq > self.context_through:
            self.context.append(payload)
            self.hydrated_context.append(self.hydrated[-1])

    def _note_compaction(self, entry: Dict[str, Any]) -> None:
        if entry.get("type") not in {"compaction", "compacted"}:
            return
        self.compactions.append(entry)
        self.latest_compaction = entry
        self.context = []
        self.hydrated_context = []
        self.context_through = int(entry.get("through_seq", 0) or 0)
        system = entry.get("system")
        if not isinstance(system, dict):
            system = next((item.get("message") for item in self.entries
                           if item.get("type") == "message"
                           and isinstance(item.get("message"), dict)
                           and item["message"].get("role") == "system"), None)
        if isinstance(system, dict):
            item = dict(system)
            self.context.append(item)
            self.hydrated_context.append(Message.model_validate(hydrate(item, self.directory)))
        summary = entry.get("summary")
        if isinstance(summary, dict):
            item = dict(summary)
            self.context.append(item)
            self.hydrated_context.append(Message.model_validate(hydrate(item, self.directory)))
        elif isinstance(summary, str) and summary:
            item = {"role": str(entry.get("summary_role") or "user"), "content": summary}
            self.context.append(item)
            self.hydrated_context.append(Message.model_validate(item))

    def _note_checkpoint(self, entry: Dict[str, Any]) -> None:
        if entry.get("type") == "checkpoint":
            self.latest_checkpoint = entry

    def _note_child(self, entry: Dict[str, Any]) -> None:
        kind = entry.get("type")
        if kind == "spawn":
            child_id = str(entry.get("child_id") or "")
            if not child_id:
                return
            metadata = dict(entry.get("metadata") or {})
            self.children[child_id] = {
                **metadata,
                "status": str(entry.get("status") or "running"),
                "output_text": str(entry.get("output_text") or ""),
            }
            if child_id not in self.child_order:
                self.child_order.append(child_id)
        elif kind == "spawn_status":
            child_id = str(entry.get("child_id") or "")
            child = self.children.get(child_id)
            if child is None:
                return
            child["status"] = str(entry.get("status") or child["status"])
            child["output_text"] = str(entry.get("output_text") or child.get("output_text") or "")

    def _note_listing(self, entry: Dict[str, Any]) -> None:
        if entry.get("type") == "spawn":
            child_session = str(entry.get("session_id") or "")
            if child_session:
                self.child_ids.add(child_session)
        payload = JsonlPersistence._message_payload_from_entry(entry)
        if payload is None:
            return
        self.message_count += 1
        if self.first_message:
            return
        text = text_from_content(payload.get("content")).strip()
        if payload.get("role") == "user" and text and not text.startswith(COMPACTED_CONTEXT_MARK):
            self.first_message = text

    def context_payloads(self) -> List[Dict[str, Any]]:
        if self.latest_compaction is None:
            return list(self.messages)
        return list(self.context)

    def listing(self, size: int) -> Dict[str, Any]:
        return {
            "version": 1,
            "transcript_size": size,
            "message_count": self.message_count,
            "first_message": self.first_message,
            "child_ids": sorted(self.child_ids),
        }


class JsonlPersistence:
    """Append-only JSONL store for harness conversations, checkpoints, and journal."""

    def __init__(self, root: Union[str, Path]) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._indexes: Dict[str, _SessionIndex] = {}
        self._listing_sizes: Dict[str, int] = {}
        self._held: Dict[str, list[int]] = {}
        # Product that owns new sessions ("tui", "zeron", ...). Empty means unknown.
        self.client: str = ""
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
            "client": self.client or "",
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
        self._indexes.pop(session_id, None)

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
        """Publish metadata, compaction and checkpoint snapshots for ``entries``.

        ``updated`` is the append path: ``entries`` are the lines just written
        and every artifact is published. Otherwise ``entries`` is a whole
        journal that was just read, and only artifacts that are missing or
        differ from what the journal implies are rewritten (crash repair).
        """
        write = snapshot if updated else refresh_snapshot
        metadata = self._require_version(session_id) or {}
        directory = self.session_dir(session_id)
        created = next((item.get("created_at") for item in entries
                        if item.get("type") == "header"), None) or _utc_now()
        write(self._metadata_path(session_id), {
            **metadata, "version": 1, "session_id": session_id,
            "created_at": metadata.get("created_at") or created,
            "updated_at": _utc_now() if updated else metadata.get("updated_at", created),
        })
        checkpoint: Optional[Dict[str, Any]] = None
        for entry in entries:
            if entry.get("type") in {"compaction", "compacted"}:
                seq = entry.get("seq", 0)
                if isinstance(seq, bool) or not isinstance(seq, int):
                    continue
                write(safe_path(directory, "compactions", f"{seq}.json"), {**entry, "version": 1})
            elif entry.get("type") == "checkpoint":
                # Each checkpoint replaces the file; only the last one survives.
                checkpoint = entry
        if checkpoint is not None:
            write(safe_path(directory, "checkpoint.json"),
                  {key: value for key, value in {**checkpoint, "version": 1}.items()
                   if key != "messages"})

    def _read_entries(self, session_id: str) -> List[Dict[str, Any]]:
        """The journal, parsed once per process and then kept current by appends.

        The transcript only grows, and every append in this process updates
        the cache and its size mark under the session lock. A size that still
        matches the mark means nothing else wrote, so the cached list is
        returned without re-reading or republishing artifacts. Any other size
        (another process appended, a torn write, first use) re-reads the file
        and repairs the artifacts.
        """
        with self._session_lock(session_id):
            self._sync_legacy(session_id)
            self._require_version(session_id)
            path = self._path(session_id)
            mark = self._mark(path)
            index = self._indexes.get(session_id)
            if index is not None and index.size == mark:
                return index.entries
            entries = self._load_transcript(path) if mark >= 0 else []
            if mark >= 0:
                self._artifacts(session_id, entries, updated=False)
            index = self._indexes.setdefault(session_id, _SessionIndex(self.session_dir(session_id)))
            index.reset(entries, mark)
            return entries

    def _cached_entries(self, session_id: str) -> List[Dict[str, Any]]:
        """Return the journal without reading it when its cached size is current."""
        path = self._path(session_id)
        mark = self._mark(path)
        index = self._indexes.get(session_id)
        if index is not None and index.size == mark:
            return index.entries
        return self._read_entries(session_id)

    def _stamp_client(self, session_id: str) -> None:
        """Record the product once. A later client must not overwrite it."""
        client = self.client or ""
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
            index = self._indexes.get(session_id)
            if index is None or index.size != mark:
                index = self._indexes.setdefault(session_id, _SessionIndex(self.session_dir(session_id)))
                index.reset(self._load_transcript(path) if mark >= 0 else [], mark)
            # A crash mid-append leaves a torn last line. Start on a fresh line
            # so the fragment stays one skipped line and does not swallow this
            # record. This costs a one-byte read per append.
            separator = b"" if self._ends_with_newline(path, mark) else b"\n"
            entries = archive(entries, self.session_dir(session_id))
            append_bytes(path, separator + self._encode(entries))
            index.extend(entries, path.stat().st_size)
            self._artifacts(session_id, entries)
            self._refresh_listing(session_id)

    @staticmethod
    def _ends_with_newline(path: Path, size: int) -> bool:
        if size <= 0:
            return True
        with path.open("rb") as handle:
            handle.seek(size - 1)
            return handle.read(1) == b"\n"

    @staticmethod
    def _max_seq(entries: List[Dict[str, Any]]) -> int:
        return max((_entry_seq(entry) for entry in entries), default=0)

    def _next_seq(self, session_id: str) -> int:
        """One past the highest seq in the cached journal of ``session_id``."""
        return self._indexes[session_id].high_seq + 1

    def _header(self, session_id: str) -> Dict[str, Any]:
        return {"type": "header", "session_id": session_id, "seq": 1, "created_at": _utc_now()}

    def _message_entry(self, payload: Dict[str, Any], *, seq: int) -> Dict[str, Any]:
        role = str(payload.get("role") or "message")
        event_type = "tool_result" if role == "tool" else role
        return {"type": "message", "event_type": event_type, "seq": seq, "message": payload, **payload}

    @staticmethod
    def _message_payload_from_entry(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
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

    def _listing_path(self, session_id: str) -> Path:
        return safe_path(self.session_dir(session_id), "listing.json")

    def _listing_from_entries(self, entries: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        """Extract the few fields the session picker displays."""
        message_count = 0
        first_message = ""
        child_ids: set[str] = set()
        for entry in entries:
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
        return {
            "version": 1,
            "transcript_size": 0,
            "message_count": message_count,
            "first_message": first_message,
            "child_ids": sorted(child_ids),
        }

    def _read_listing(self, session_id: str, transcript_size: int) -> Optional[Dict[str, Any]]:
        path = self._listing_path(session_id)
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if (
            isinstance(saved, dict)
            and saved.get("version") == 1
            and saved.get("transcript_size") == transcript_size
            and isinstance(saved.get("message_count"), int)
            and isinstance(saved.get("first_message"), str)
            and isinstance(saved.get("child_ids"), list)
        ):
            return saved
        return None

    def _refresh_listing(self, session_id: str) -> Dict[str, Any]:
        index = self._indexes[session_id]
        size = index.size
        if self._listing_sizes.get(session_id) == size:
            saved = self._read_listing(session_id, size)
            if saved is not None:
                return saved
        listing = index.listing(size)
        refresh_snapshot(self._listing_path(session_id), listing)
        self._listing_sizes[session_id] = size
        return listing

    def _session_listing(self, session_id: str) -> Dict[str, Any]:
        size = self._mark(self._path(session_id))
        index = self._indexes.get(session_id)
        if index is not None and index.size == size:
            return self._refresh_listing(session_id)
        saved = self._read_listing(session_id, size)
        if saved is not None:
            return saved
        self._read_entries(session_id)
        return self._refresh_listing(session_id)

    def _transcript_messages(self, entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Return every persisted message, including messages before compaction."""
        return [payload for entry in entries
                if (payload := self._message_payload_from_entry(entry)) is not None]

    async def append_event(self, *, event_type: str, payload: dict[str, Any]) -> None:
        if event_type in _SKIP_EVENTS:
            return
        session_id = str(payload.get("session_id") or "")
        if not session_id:
            return
        with self._lock, self._session_lock(session_id):
            entries = self._cached_entries(session_id)
            index = self._indexes[session_id]
            run_id = payload.get("run_id")
            seq = payload.get("seq")
            if run_id and isinstance(seq, int) and (str(run_id), seq) in index.event_keys:
                return
            outgoing: List[Dict[str, Any]] = []
            if not entries:
                outgoing.append(self._header(session_id))
            outgoing.append(
                {
                    "type": event_type,
                    "event_type": event_type,
                    "seq": seq if isinstance(seq, int) else self._next_seq(session_id),
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
            if event_type in TERMINAL_EVENT_TYPES:
                self._append_collection_overlays(
                    session_id,
                    run_id=str(run_id) if run_id else None,
                )

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
            self._read_entries(session_id)
            return self._append_collection_overlays(session_id, run_id=run_id, keys=keys)

    def _append_collection_overlays(
        self,
        session_id: str,
        *,
        run_id: str | None = None,
        keys: Sequence[tuple[str, int]] | None = None,
    ) -> list[tuple[str, int]]:
        index = self._indexes[session_id]
        selected = run_id or index.latest_terminal_run
        targets = list(keys) if keys is not None else index.collectable.get(selected, [])
        pending = [key for key in targets if key not in index.collected]
        if not pending:
            return []
        next_seq = index.high_seq + 1
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
            directory = self.session_dir(session_id)
            collected = self._indexes[session_id].collected
        events = [
            (str(entry.get("event_type") or ""), entry.get("payload"))
            for entry in entries
            if entry.get("event_type") and entry.get("type") != "message" and isinstance(entry.get("payload"), dict)
        ]
        return apply_collection([(kind, hydrate(payload, directory)) for kind, payload in events], collected=collected)

    async def load_children(self, *, parent_session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            self._cached_entries(parent_session_id)
            index = self._indexes[parent_session_id]
            return [dict(index.children[child_id]) for child_id in index.child_order]

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
            index = self._indexes[session_id]
            stored = index.context_payloads()
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
            if len(incoming) >= len(stored) and incoming[: len(stored)] == stored:
                extra = incoming[len(stored) :]
                if extra:
                    next_seq = self._next_seq(session_id)
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
                    next_seq = self._next_seq(session_id)
                    self._append_entries(
                        session_id,
                        [self._message_entry(item, seq=next_seq + index) for index, item in enumerate(extra)],
                    )
                return
            # A rewrite means the harness compacted its runtime context. Keep
            # the complete transcript and append only a checkpoint plus the
            # retained suffix; compaction must never erase TUI history.
            previous_seq = self._next_seq(session_id) - 1
            candidates = list(incoming)
            system = next((item for item in candidates if item.get("role") == "system"), None)
            if system is not None:
                candidates.remove(system)
            summary = candidates.pop(0) if candidates else {"role": "user", "content": ""}
            next_seq = self._next_seq(session_id)
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

    def _load_messages(self, session_id: str, *, transcript: bool) -> tuple[List[Message], List[Message]]:
        """Return both histories from the incremental index, hydrating once."""
        with self._lock:
            self._cached_entries(session_id)
            index = self._indexes[session_id]
            if not transcript:
                return [], list(index.hydrated_context)
            return list(index.hydrated), list(index.hydrated_context)

    async def load_conversation(self, *, session_id: str) -> List[Message]:
        """Load the reconstructed model context (runtime view)."""
        _, context = self._load_messages(session_id, transcript=False)
        return context

    async def load_transcript(self, *, session_id: str) -> List[Message]:
        """Load the complete persisted transcript for the TUI/history view."""
        history, _ = self._load_messages(session_id, transcript=True)
        return history

    async def load_resume(self, *, session_id: str) -> tuple[List[Message], List[Message]]:
        """Load visible history and model context from one journal read."""
        return self._load_messages(session_id, transcript=True)

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
                try:
                    meta = self._read_metadata(session_id)
                except ValueError:
                    meta = None
                client = str(meta.get("client") or "") if isinstance(meta, dict) else ""
                listing = self._session_listing(session_id)
                message_count = int(listing["message_count"])
                first_message = str(listing["first_message"])
                child_ids.update(str(child_id) for child_id in listing["child_ids"])
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
        # The journal already holds the messages; do not dump them every turn.
        payload = checkpoint.model_dump(exclude={"messages"})
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
            self._cached_entries(session_id)
            latest = self._indexes[session_id].latest_checkpoint
        metadata = latest.get("metadata") if isinstance(latest, dict) else None
        return str(metadata.get("goal") or "") if isinstance(metadata, dict) else ""

    async def load_checkpoint(self, *, session_id: str) -> Optional[Checkpoint]:
        with self._lock:
            self._cached_entries(session_id)
            index = self._indexes[session_id]
            latest = index.latest_checkpoint
            if latest is None:
                return None
            directory = self.session_dir(session_id)
            payload = hydrate({key: value for key, value in latest.items() if key != "type"}, directory)
            payload.setdefault("session_id", session_id)
            payload["messages"] = [
                Message.model_validate(hydrate(message, directory)) for message in index.context_payloads()
            ]
        return Checkpoint.model_validate(payload)

    async def load_compactions(self, session_id: str) -> List[Dict[str, Any]]:
        """Return compaction boundaries in transcript order, with hydrated content."""
        with self._lock:
            self._read_entries(session_id)
            index = self._indexes[session_id]
            directory = self.session_dir(session_id)
            return [hydrate(entry, directory) for entry in index.compactions]
