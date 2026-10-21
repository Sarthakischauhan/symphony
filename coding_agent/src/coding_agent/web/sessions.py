"""Web workers speak the stdio protocol; every read goes through its frames.

``Worker`` owns one ``symphony stdio --client web`` process. Frames that answer a
pending request (matched by ``request_id``) resolve that request; every other
frame joins the ordered, replayable event log the browser streams over SSE.

``Sessions`` keeps one idle *control* worker for reads that are not tied to an
open session (session list, history, model and command catalogs, workspace
info) plus one worker per session the browser is driving.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import IO, TypedDict

JsonObject = dict[str, object]

REQUEST_TIMEOUT = 60.0
STARTUP_TIMEOUT = 60.0


class WorkerError(RuntimeError):
    """The worker rejected a request or is not running."""


class Event(TypedDict):
    id: int
    data: JsonObject


@dataclass(frozen=True)
class Ready:
    session_id: str
    model: str
    workspace: str
    branch: str


def text(frame: JsonObject, key: str) -> str:
    value = frame.get(key)
    return value if isinstance(value, str) else ""


def objects(frame: JsonObject, key: str) -> list[JsonObject]:
    value = frame.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def strings(frame: JsonObject, key: str) -> list[str]:
    value = frame.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _parse(line: str) -> JsonObject | None:
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


class Worker:
    def __init__(self, workspace: Path, session_id: str, model: str | None = None) -> None:
        self.condition = threading.Condition()
        self.events: list[Event] = []
        self.waiting: set[str] = set()
        self.replies: dict[str, JsonObject] = {}
        self.workspace = workspace
        command = [
            sys.executable, "-m", "coding_agent.web.worker",
            "--workspace", str(workspace), "--session-id", session_id,
        ]
        if model:
            command += ["--model", model]
        self.process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1,
            # The host owns shutdown via interrupt + stdin EOF. Terminal Ctrl-C
            # must not interrupt asyncio (or tools) in each worker independently.
            start_new_session=True,
        )
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        with self.condition:
            if not self.condition.wait_for(lambda: bool(self.events) or self.process.poll() is not None,
                                           timeout=STARTUP_TIMEOUT):
                self.close()
                raise WorkerError("Agent startup timed out")
            first = self.events[0]["data"] if self.events else {}
        if text(first, "type") != "ready":
            self.close()
            raise WorkerError(text(first, "message") or "Agent failed to start; check provider configuration")
        self.ready = Ready(
            session_id=text(first, "session_id"),
            model=text(first, "model"),
            workspace=text(first, "workspace"),
            branch=text(first, "branch"),
        )

    @property
    def alive(self) -> bool:
        return self.process.poll() is None

    def _stdout(self) -> IO[str]:
        stream = self.process.stdout
        if stream is None:
            raise WorkerError("Worker has no output stream")
        return stream

    def _read(self) -> None:
        for line in self._stdout():
            frame = _parse(line)
            if frame is not None:
                self.append(frame)
        self.append({"type": "done", "status": "worker_exited"})

    def append(self, frame: JsonObject) -> None:
        with self.condition:
            request_id = text(frame, "request_id")
            if request_id in self.waiting:
                self.replies[request_id] = frame
            else:
                self.events.append({"id": len(self.events) + 1, "data": frame})
            self.condition.notify_all()

    def command(self, frame: JsonObject) -> None:
        with self.condition:
            stream = self.process.stdin
            if not self.alive or stream is None:
                raise WorkerError("Worker exited; resume this session to recover")
            stream.write(json.dumps(frame) + "\n")
            stream.flush()

    def request(self, kind: str, **fields: str) -> JsonObject:
        """Send one request frame and wait for the reply with its ``request_id``."""
        request_id = f"web-{uuid.uuid4()}"
        with self.condition:
            self.waiting.add(request_id)
            try:
                self.command({"type": kind, "request_id": request_id, **fields})
                if not self.condition.wait_for(
                    lambda: request_id in self.replies or not self.alive, timeout=REQUEST_TIMEOUT,
                ):
                    raise WorkerError(f"{kind} timed out")
                reply = self.replies.pop(request_id, None)
            finally:
                self.waiting.discard(request_id)
        if reply is None:
            raise WorkerError("Worker exited; resume this session to recover")
        if text(reply, "type") == "error":
            raise WorkerError(text(reply, "message") or f"{kind} failed")
        return reply

    def close(self) -> None:
        if not self.alive:
            return
        try:
            self.command({"type": "interrupt"})
            if self.process.stdin is not None:
                self.process.stdin.close()
            self.process.wait(timeout=5)
        except (OSError, WorkerError, subprocess.TimeoutExpired):
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()


class Sessions:
    def __init__(self, workspace: Path, model: str | None = None) -> None:
        self.workspace, self.model = workspace, model
        self.workers: dict[str, Worker] = {}
        self.baselines: dict[str, JsonObject] = {}
        self.lock = threading.RLock()
        self._control: Worker | None = None
        self._closed = False

    def control(self) -> Worker:
        """An idle worker on a fresh, never-persisted session, for catalog reads."""
        with self.lock:
            if self._closed:
                raise WorkerError("Web server is shutting down")
            if self._control is None or not self._control.alive:
                self._control = Worker(self.workspace, str(uuid.uuid4()), self.model)
            return self._control

    def warm(self) -> None:
        """Start the control worker in the background so the first page load does not wait for it."""

        def start() -> None:
            try:
                self.control()
            except (WorkerError, OSError):
                pass  # The first API request retries and reports the failure.

        threading.Thread(target=start, name="symphony-web-warm", daemon=True).start()

    def info(self) -> JsonObject:
        ready = self.control().ready
        path = Path(ready.workspace or str(self.workspace))
        home = Path.home()
        display = f"~/{path.relative_to(home)}" if path.is_relative_to(home) else str(path)
        return {"path": str(path), "display": display, "name": path.name, "branch": ready.branch}

    def models(self) -> JsonObject:
        return registry(self.control().request("model/list"))

    def commands(self) -> list[JsonObject]:
        return objects(self.control().request("command/list"), "commands")

    def owned(self, session_id: str) -> Worker | None:
        worker = self.workers.get(session_id)
        return worker if worker is not None and worker.alive else None

    def model_of(self, session_id: str) -> str:
        worker = self.owned(session_id)
        return worker.ready.model if worker is not None else ""

    def listing(self) -> list[JsonObject]:
        return [
            {**item, "owned": self.owned(text(item, "session_id")) is not None}
            for item in objects(self.control().request("session/list"), "sessions")
        ]

    def history(self, session_id: str) -> JsonObject:
        reply = self.control().request("session/history", session_id=session_id)
        return {"messages": reply.get("messages", []), "events": reply.get("events", []),
                "children": reply.get("children", [])}

    def resume(self, session_id: str | None = None, model: str | None = None) -> str:
        """Open a worker on ``session_id`` (a new session when omitted).

        A different model on a live worker goes through the protocol's
        ``model`` request, which the worker rejects during an active run.
        """
        with self.lock:
            if self._closed:
                raise WorkerError("Web server is shutting down")
            live = self.owned(session_id) if session_id else None
            if live is not None and session_id is not None:
                if model and model != live.ready.model:
                    reply = live.request("model", model=model)
                    live.ready = Ready(live.ready.session_id, text(reply, "model"), live.ready.workspace,
                                       live.ready.branch)
                return session_id
            sid = session_id or str(uuid.uuid4())
            baseline = self.history(sid) if session_id else {"messages": [], "events": [], "children": []}
            worker = Worker(self.workspace, sid, model or self.model)
            self.workers[sid] = worker
            self.baselines[sid] = baseline
            return sid

    def close(self) -> None:
        # Warmup and resume hold the same lock while starting a worker. Wait for
        # them before taking the snapshot so no process escapes cleanup.
        with self.lock:
            self._closed = True
            workers = [*self.workers.values(), *([self._control] if self._control else [])]
        for worker in workers:
            worker.close()


def registry(catalog: JsonObject) -> JsonObject:
    """Group the stdio ``models`` reply by provider for the chat SDK model picker."""
    providers: dict[str, JsonObject] = {}
    entries: dict[str, list[JsonObject]] = {}
    for item in objects(catalog, "models"):
        provider, model_id = text(item, "provider"), text(item, "id")
        if provider not in providers:
            entries[provider] = []
            providers[provider] = {"id": provider, "label": provider, "defaultModel": model_id,
                                   "models": entries[provider]}
        entry: JsonObject = {"id": model_id, "label": text(item, "label")}
        limit = item.get("context_limit")
        if isinstance(limit, int) and limit > 0:
            # contextWindow drives the picker's "128K context window" line; a
            # null limit omits it.
            entry["contextWindow"] = limit
        levels = strings(item, "reasoning_levels")
        if levels:
            entry["thinkingLevels"] = levels
        entries[provider].append(entry)
    default = text(catalog, "default")
    # The default's provider is the one its own row names.
    provider = next(
        (text(item, "provider") for item in objects(catalog, "models") if text(item, "id") == default), ""
    )
    if provider in providers:
        providers[provider]["defaultModel"] = default
    return {
        "defaultProviderId": provider if provider in providers else next(iter(providers), ""),
        "providers": list(providers.values()),
        "default": default,
    }
