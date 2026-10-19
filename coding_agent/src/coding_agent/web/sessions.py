"""Session persistence reads and serialized worker ownership for the web host."""

import asyncio
import json
import subprocess
import sys
import threading
import uuid
from dataclasses import asdict
from pathlib import Path

from coding_agent.addons.persistence import JsonlPersistence, active_session_ids, sessions_dir
from coding_agent.commands.catalog import EFFORTS


class Worker:
    def __init__(self, workspace, session_id, model):
        self.condition = threading.Condition()
        self.events = []
        self.pending = {}
        self.busy = False
        self.artifacts = {}
        self.tool_inputs = {}
        self.workspace = workspace
        self.model = model or ""
        self.process = subprocess.Popen(
            [sys.executable, "-m", "coding_agent.web.worker", str(workspace), session_id, model or ""],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        with self.condition:
            if not self.condition.wait_for(lambda: self.events or self.process.poll() is not None, timeout=30):
                self.close()
                raise RuntimeError("Agent startup timed out")
            if not self.events or self.events[0]["data"].get("type") != "ready":
                self.close()
                raise RuntimeError("Agent failed to start; check provider configuration and server stderr")

    def _read(self):
        for line in self.process.stdout:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            self.append(data)
        self.append({"type": "done", "status": "worker_exited"})

    def append(self, data):
        with self.condition:
            self.events.append({"id": len(self.events) + 1, "data": data})
            payload = data.get("payload", {})
            if data.get("type") == "ready" and data.get("model"):
                self.model = data["model"]
            if data.get("event") == "tool_execution_started":
                self.tool_inputs[payload.get("tool_call_id")] = payload
            if data.get("event") == "tool_execution_completed" and payload.get("status") == "success":
                call = self.tool_inputs.get(payload.get("tool_call_id"), {})
                if call.get("tool_name") == "write_file":
                    raw = call.get("arguments", {}).get("path", "")
                    path = (self.workspace / raw).resolve()
                    if path.is_relative_to(self.workspace) and path.is_file():
                        self.artifacts[payload["tool_call_id"]] = path
            if data.get("type") == "input_requested":
                self.pending[data["request_id"]] = data
            if data.get("type") == "done":
                self.pending.clear()
                self.busy = False
            self.condition.notify_all()

    def command(self, data):
        with self.condition:
            if self.process.poll() is not None:
                raise RuntimeError("Worker exited; resume this session to recover")
            self.process.stdin.write(json.dumps(data) + "\n")
            self.process.stdin.flush()
            if data.get("type") == "answer":
                self.pending.pop(data["request_id"], None)

    def close(self):
        if self.process.poll() is None:
            try:
                self.command({"type": "interrupt"})
                self.process.stdin.close()
                self.process.wait(timeout=5)
            except (BrokenPipeError, OSError, RuntimeError, subprocess.TimeoutExpired):
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()


class Sessions:
    def __init__(self, workspace, model=None):
        self.workspace, self.model = workspace, model
        self.persistence = JsonlPersistence(sessions_dir(workspace, client="tui"))
        self.workers = {}
        self.lock = threading.RLock()
        self.catalog = None

    def info(self):
        try:
            branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=self.workspace,
                capture_output=True, text=True, timeout=2, check=False,
            ).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            branch = ""
        home = Path.home()
        display = f"~/{self.workspace.relative_to(home)}" if self.workspace.is_relative_to(home) else str(self.workspace)
        return {"path": str(self.workspace), "display": display, "name": self.workspace.name, "branch": branch}

    def models(self):
        """The provider catalog in the chat SDK registry shape, built once by a worker."""
        with self.lock:
            if self.catalog is None:
                result = subprocess.run(
                    [sys.executable, "-m", "coding_agent.web.worker", "--models", str(self.workspace), self.model or ""],
                    capture_output=True, text=True, timeout=60, check=False,
                )
                lines = result.stdout.strip().splitlines()
                if result.returncode or not lines:
                    raise RuntimeError("Could not load models; check provider configuration")
                self.catalog = registry(json.loads(lines[-1]))
            return self.catalog

    def listing(self):
        active = active_session_ids()
        return [
            {**asdict(item), "active": item.session_id in active, "owned": item.session_id in self.workers}
            for item in asyncio.run(self.persistence.list_sessions())
        ]

    def history(self, session_id):
        return {
            "messages": [
                m.model_dump(mode="json") for m in asyncio.run(self.persistence.load_transcript(session_id=session_id))
            ],
            "events": asyncio.run(self.persistence.load_events(session_id=session_id)),
            "children": asyncio.run(self.persistence.load_children(parent_session_id=session_id)),
        }

    def resume(self, session_id=None, model=None):
        with self.lock:
            session_id = session_id or str(uuid.uuid4())
            worker = self.workers.get(session_id)
            if worker and worker.process.poll() is None:
                if not model or model == worker.model:
                    return session_id
                # A model switch restarts the worker on the persisted session.
                with worker.condition:
                    if worker.busy:
                        raise RuntimeError("Stop the running task before switching models")
                worker.close()
            if session_id in active_session_ids():
                raise RuntimeError("Session is owned by another live Symphony process")
            baseline = self.history(session_id)
            worker = Worker(self.workspace, session_id, model or self.model)
            worker.baseline = baseline
            self.workers[session_id] = worker
            return session_id

    def close(self):
        for worker in self.workers.values():
            worker.close()


def registry(catalog):
    """Group the stdio model catalog by provider for the chat SDK model picker."""
    providers = {}
    for item in catalog.get("models", []):
        entry = providers.setdefault(
            item["provider"], {"id": item["provider"], "label": item["provider"], "defaultModel": item["id"], "models": []}
        )
        levels = [level for level in item.get("reasoning_levels") or [] if level in EFFORTS]
        model = {"id": item["id"], "label": item["label"]}
        if item.get("context_limit"):
            model["description"] = f"{item['context_limit'] // 1000}k context"
        if levels:
            model["thinkingLevels"] = levels
        entry["models"].append(model)
    default = catalog.get("default", "")
    provider = default.partition(":")[0]
    if provider in providers:
        providers[provider]["defaultModel"] = default
    return {
        "defaultProviderId": provider if provider in providers else next(iter(providers), ""),
        "providers": list(providers.values()),
        "default": default,
    }
